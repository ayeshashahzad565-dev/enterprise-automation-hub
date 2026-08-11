"use client";

import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  type Edge,
  type Node,
  type NodeTypes,
  type OnNodeDrag,
} from "@xyflow/react";
// React Flow's base stylesheet is imported from app/layout.tsx instead of
// here — see that import's comment for why.
import { useEffect, useMemo, useState } from "react";

import {
  StageNode,
  type StageNodeData,
  type StageNodeType,
} from "@/features/workflow-designer/components/workflow-canvas/stage-node";
import type { StageDefinition } from "@/types/workflow-definition";

const NODE_TYPES: NodeTypes = { stage: StageNode };
const SPACING = 240;

function layout(
  stages: StageDefinition[],
  orientation: "horizontal" | "vertical",
  selectedOrder: number | null,
  readOnly: boolean,
  handlers: {
    onSelect: (order: number) => void;
    onRemove: (order: number) => void;
    onDuplicate: (order: number) => void;
  },
): { nodes: Node[]; edges: Edge[] } {
  const ordered = [...stages].sort((a, b) => a.order - b.order);
  const axis = (index: number) => index * SPACING;
  const pos = (index: number) =>
    orientation === "horizontal" ? { x: axis(index), y: 0 } : { x: 0, y: axis(index) };

  const start: Node = {
    id: "start",
    type: "input",
    position: pos(0),
    data: { label: "Start" },
    draggable: false,
  };
  const end: Node = {
    id: "end",
    type: "output",
    position: pos(ordered.length + 1),
    data: { label: "End" },
    draggable: false,
  };

  const stageNodes: StageNodeType[] = ordered.map((stage, index) => ({
    id: `stage-${stage.order}`,
    type: "stage",
    position: pos(index + 1),
    data: {
      stage,
      isSelected: stage.order === selectedOrder,
      readOnly,
      onSelect: () => handlers.onSelect(stage.order),
      onRemove: () => handlers.onRemove(stage.order),
      onDuplicate: () => handlers.onDuplicate(stage.order),
    },
  }));

  const chain: Node[] = [start, ...stageNodes, end];
  const edges: Edge[] = [];
  for (let i = 0; i < chain.length - 1; i += 1) {
    edges.push({
      id: `${chain[i].id}->${chain[i + 1].id}`,
      source: chain[i].id,
      target: chain[i + 1].id,
      type: "smoothstep",
      animated: false,
    });
  }

  return { nodes: chain, edges };
}

export function WorkflowCanvas({
  stages,
  selectedOrder,
  onSelectStage,
  onReorderStage,
  onRemoveStage,
  onDuplicateStage,
  orientation = "horizontal",
  readOnly = false,
}: {
  stages: StageDefinition[];
  selectedOrder: number | null;
  onSelectStage: (order: number) => void;
  onReorderStage: (fromOrder: number, toOrder: number) => void;
  onRemoveStage: (order: number) => void;
  onDuplicateStage: (order: number) => void;
  orientation?: "horizontal" | "vertical";
  readOnly?: boolean;
}) {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () =>
      layout(stages, orientation, selectedOrder, readOnly, {
        onSelect: onSelectStage,
        onRemove: onRemoveStage,
        onDuplicate: onDuplicateStage,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stages, orientation, selectedOrder, readOnly],
  );

  const [nodes, setNodes] = useState<Node[]>(initialNodes);
  const [edges, setEdges] = useState<Edge[]>(initialEdges);

  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges]);

  const handleNodeDragStop: OnNodeDrag<Node> = (_event, draggedNode) => {
    if (draggedNode.type !== "stage" || readOnly) return;
    const stageData = draggedNode.data as StageNodeData;
    const stageNodes = nodes.filter((n): n is StageNodeType => n.type === "stage");
    const axisOf = (n: Node) => (orientation === "horizontal" ? n.position.x : n.position.y);
    const withUpdatedPosition = stageNodes.map((n) => (n.id === draggedNode.id ? draggedNode : n));
    const sorted = [...withUpdatedPosition].sort((a, b) => axisOf(a) - axisOf(b));
    const fromOrder = stageData.stage.order;
    const newIndex = sorted.findIndex((n) => n.id === draggedNode.id);
    const toOrder = newIndex + 1;
    if (toOrder !== fromOrder) onReorderStage(fromOrder, toOrder);
  }

  return (
    <ReactFlowProvider>
      <div className="h-full w-full">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          onNodesChange={(changes) => setNodes((current) => applyNodeChanges(changes, current))}
          onNodeDragStop={handleNodeDragStop}
          nodesConnectable={false}
          elementsSelectable
          // `fitView` (the boolean prop) only runs once, at mount — racing
          // react-resizable-panels' own async pixel-size calculation for
          // this canvas's containing panel. When it loses that race, React
          // Flow computes its initial zoom/pan from a still-0-sized
          // container (logging its own "parent container needs a width
          // and a height" warning) and never recalculates, leaving the
          // view zoomed/panned to somewhere nonsensical. Calling
          // instance.fitView() from onInit, deferred one frame via
          // requestAnimationFrame, runs it after the browser has actually
          // finished laying out the page instead.
          //
          // padding: 0.3 leaves a real margin around the fitted diagram —
          // without it a short chain (e.g. Start -> two stages -> End) fits
          // so tightly that the outermost nodes sit flush against the
          // canvas edge, colliding with the zoom Controls overlay.
          onInit={(instance) => requestAnimationFrame(() => instance.fitView({ padding: 0.3 }))}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </ReactFlowProvider>
  );
}
