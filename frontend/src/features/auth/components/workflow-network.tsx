"use client";

import { useEffect, useRef } from "react";

/**
 * The login screen's brand-panel hero: a "living workflow network" — nodes
 * standing in for departments/approval stages, connected by an organic
 * mesh, with a handful of small glowing packets ("approval requests")
 * continuously traveling between them. Replaces the earlier static SVG
 * graph (a fixed node layout with a CSS dash-offset animation) with a real
 * particle/graph simulation.
 *
 * Deliberately Canvas 2D, not WebGL or dozens of DOM nodes: at this scale
 * (~20-30 nodes, a handful of concurrent packets) Canvas comfortably holds
 * 60fps, and avoids a WebGL dependency for a decorative panel. All
 * animation state (nodes, edges, packets, ripples, mouse parallax) lives in
 * plain objects inside this effect's closure, not React state — nothing
 * here ever triggers a React re-render; every frame writes straight to the
 * canvas via a single requestAnimationFrame loop.
 */

interface Node {
  baseX: number;
  baseY: number;
  x: number;
  y: number;
  r: number;
  isHub: boolean;
  driftPhaseX: number;
  driftPhaseY: number;
  driftAmp: number;
  glowStart: number | null;
}

interface Edge {
  a: number;
  b: number;
  length: number;
}

interface Packet {
  edgeIndex: number;
  from: number;
  to: number;
  t: number;
  speed: number;
  hops: number;
  maxHops: number;
}

interface Ripple {
  x: number;
  y: number;
  start: number;
}

interface Orb {
  baseX: number;
  baseY: number;
  x: number;
  y: number;
  r: number;
  driftPhaseX: number;
  driftPhaseY: number;
  driftAmp: number;
}

const GLOW_DURATION_MS = 1300;
const RIPPLE_DURATION_MS = 1100;
const RIPPLE_MAX_RADIUS = 30;
const MAX_PACKETS = 6;
const PACKET_SPAWN_MIN_MS = 1400;
const PACKET_SPAWN_MAX_MS = 3200;
const PACKET_SPEED_PX_PER_MS = 0.045;
const DRIFT_ANGULAR_SPEED = 0.00018;
const PARALLAX_EASE = 0.04;
const MERGE_WINDOW_MS = 260;

function resolveCssColorChannels(varName: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const probe = document.createElement("span");
  probe.style.color = `var(${varName})`;
  probe.style.position = "absolute";
  probe.style.opacity = "0";
  probe.style.pointerEvents = "none";
  document.body.appendChild(probe);
  const resolved = getComputedStyle(probe).color;
  document.body.removeChild(probe);
  const match = /rgba?\(([^)]+)\)/.exec(resolved);
  if (!match) return fallback;
  const parts = match[1].split(",").slice(0, 3).map((part) => part.trim());
  return parts.length === 3 ? parts.join(", ") : fallback;
}

/** Rejection-sampled point scatter — organic, minimum-spacing-respecting, but not a grid. */
function scatterPoints(count: number, width: number, height: number, margin: number): Array<[number, number]> {
  const points: Array<[number, number]> = [];
  const minDist = Math.max(28, Math.sqrt((width * height) / count) * 0.55);
  let attempts = 0;
  while (points.length < count && attempts < count * 60) {
    attempts += 1;
    const x = margin + Math.random() * (width - margin * 2);
    const y = margin + Math.random() * (height - margin * 2);
    const farEnough = points.every(([px, py]) => Math.hypot(px - x, py - y) >= minDist);
    if (farEnough || attempts > count * 40) {
      points.push([x, y]);
    }
  }
  return points;
}

function buildNetwork(width: number, height: number) {
  const area = width * height;
  const nodeCount = Math.max(20, Math.min(30, Math.round(area / 24000)));
  const points = scatterPoints(nodeCount, width, height, 36);

  const nodes: Node[] = points.map(([x, y], index) => {
    const isHub = index % 5 === 0;
    return {
      baseX: x,
      baseY: y,
      x,
      y,
      r: isHub ? 4.5 + Math.random() * 1.5 : 2 + Math.random() * 1.8,
      isHub,
      driftPhaseX: Math.random() * Math.PI * 2,
      driftPhaseY: Math.random() * Math.PI * 2,
      driftAmp: 3 + Math.random() * 3,
      glowStart: null,
    };
  });

  const edgeKeys = new Set<string>();
  const edges: Edge[] = [];
  const adjacency: number[][] = nodes.map(() => []);

  nodes.forEach((node, i) => {
    const distances = nodes
      .map((other, j) => ({ j, d: i === j ? Infinity : Math.hypot(other.x - node.x, other.y - node.y) }))
      .sort((a, b) => a.d - b.d);
    const neighborCount = node.isHub ? 3 + Math.floor(Math.random() * 2) : 2;
    for (let k = 0; k < neighborCount && k < distances.length; k += 1) {
      const j = distances[k].j;
      const key = i < j ? `${i}-${j}` : `${j}-${i}`;
      if (edgeKeys.has(key)) continue;
      edgeKeys.add(key);
      const length = Math.hypot(nodes[j].x - node.x, nodes[j].y - node.y);
      edges.push({ a: i, b: j, length });
      adjacency[i].push(edges.length - 1);
      adjacency[j].push(edges.length - 1);
    }
  });

  const orbCount = Math.max(4, Math.min(6, Math.round(area / 140000)));
  const orbPoints = scatterPoints(orbCount, width, height, 40);
  const orbs: Orb[] = orbPoints.map(([x, y]) => ({
    baseX: x,
    baseY: y,
    x,
    y,
    r: 90 + Math.random() * 90,
    driftPhaseX: Math.random() * Math.PI * 2,
    driftPhaseY: Math.random() * Math.PI * 2,
    driftAmp: 8 + Math.random() * 6,
  }));

  return { nodes, edges, adjacency, orbs };
}

function otherEndpoint(edge: Edge, node: number): number {
  return edge.a === node ? edge.b : edge.a;
}

function spawnPacket(nodes: Node[], adjacency: number[][], edges: Edge[]): Packet | null {
  const candidates = nodes.map((_, i) => i).filter((i) => adjacency[i].length > 0);
  if (candidates.length === 0) return null;
  const from = candidates[Math.floor(Math.random() * candidates.length)];
  const edgeIndex = adjacency[from][Math.floor(Math.random() * adjacency[from].length)];
  const edge = edges[edgeIndex];
  return {
    edgeIndex,
    from,
    to: otherEndpoint(edge, from),
    t: 0,
    speed: PACKET_SPEED_PX_PER_MS * (0.85 + Math.random() * 0.3),
    hops: 0,
    maxHops: 3 + Math.floor(Math.random() * 4),
  };
}

export function WorkflowNetwork({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const accent = resolveCssColorChannels("--primary", "129, 140, 248");

    let network = buildNetwork(container.clientWidth || 480, container.clientHeight || 640);
    let packets: Packet[] = [];
    let ripples: Ripple[] = [];
    let nextSpawnAt = 0;
    let lastGlowNode = -1;
    let lastGlowAt = -Infinity;

    const parallax = { targetX: 0, targetY: 0, x: 0, y: 0 };
    let dpr = Math.min(window.devicePixelRatio || 1, 2);

    function resize() {
      if (!canvas || !container) return;
      const width = container.clientWidth;
      const height = container.clientHeight;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      network = buildNetwork(width, height);
      packets = [];
      ripples = [];
      nextSpawnAt = 0;
    }
    resize();

    let resizeTimer: ReturnType<typeof setTimeout> | null = null;
    const handleResize = () => {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(resize, 150);
    };
    window.addEventListener("resize", handleResize);

    const mouse = { x: null as number | null, y: null as number | null };

    function handlePointerMove(event: PointerEvent) {
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const localX = event.clientX - rect.left;
      const localY = event.clientY - rect.top;
      mouse.x = localX;
      mouse.y = localY;
      const nx = (localX / rect.width) * 2 - 1;
      const ny = (localY / rect.height) * 2 - 1;
      parallax.targetX = Math.max(-1, Math.min(1, nx));
      parallax.targetY = Math.max(-1, Math.min(1, ny));
    }
    function handlePointerLeave() {
      parallax.targetX = 0;
      parallax.targetY = 0;
      mouse.x = null;
      mouse.y = null;
    }
    container.addEventListener("pointermove", handlePointerMove);
    container.addEventListener("pointerleave", handlePointerLeave);

    let running = true;
    const handleVisibility = () => {
      running = document.visibilityState === "visible";
      if (running) lastTime = null;
    };
    document.addEventListener("visibilitychange", handleVisibility);

    function drawStaticFrame() {
      if (!canvas || !ctx || !container) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, container.clientWidth, container.clientHeight);
      for (const orb of network.orbs) {
        const gradient = ctx.createRadialGradient(orb.x, orb.y, 0, orb.x, orb.y, orb.r);
        gradient.addColorStop(0, `rgba(${accent}, 0.12)`);
        gradient.addColorStop(1, `rgba(${accent}, 0)`);
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(orb.x, orb.y, orb.r, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.lineWidth = 1;
      ctx.strokeStyle = `rgba(${accent}, 0.14)`;
      for (const edge of network.edges) {
        const a = network.nodes[edge.a];
        const b = network.nodes[edge.b];
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
      for (const node of network.nodes) {
        ctx.beginPath();
        ctx.fillStyle = "rgba(226, 232, 240, 0.32)";
        ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    if (reduceMotion) {
      drawStaticFrame();
      return () => {
        window.removeEventListener("resize", handleResize);
        container.removeEventListener("pointermove", handlePointerMove);
        container.removeEventListener("pointerleave", handlePointerLeave);
        document.removeEventListener("visibilitychange", handleVisibility);
        if (resizeTimer) clearTimeout(resizeTimer);
      };
    }

    let lastTime: number | null = null;
    let rafId = 0;

    function frame(now: number) {
      rafId = requestAnimationFrame(frame);
      if (!running || !canvas || !ctx) return;
      const dt = lastTime === null ? 16 : Math.min(now - lastTime, 48);
      lastTime = now;

      parallax.x += (parallax.targetX - parallax.x) * PARALLAX_EASE;
      parallax.y += (parallax.targetY - parallax.y) * PARALLAX_EASE;

      const { nodes, edges, adjacency, orbs } = network;

      for (const orb of orbs) {
        orb.x =
          orb.baseX + Math.sin(now * DRIFT_ANGULAR_SPEED + orb.driftPhaseX) * orb.driftAmp + parallax.x * 7;
        orb.y =
          orb.baseY + Math.cos(now * DRIFT_ANGULAR_SPEED + orb.driftPhaseY) * orb.driftAmp + parallax.y * 7;
      }
      for (const node of nodes) {
        node.x =
          node.baseX + Math.sin(now * DRIFT_ANGULAR_SPEED + node.driftPhaseX) * node.driftAmp + parallax.x * 3;
        node.y =
          node.baseY + Math.cos(now * DRIFT_ANGULAR_SPEED + node.driftPhaseY) * node.driftAmp + parallax.y * 3;
      }

      if (now >= nextSpawnAt && packets.length < MAX_PACKETS) {
        const packet = spawnPacket(nodes, adjacency, edges);
        if (packet) packets.push(packet);
        nextSpawnAt = now + PACKET_SPAWN_MIN_MS + Math.random() * (PACKET_SPAWN_MAX_MS - PACKET_SPAWN_MIN_MS);
      }

      const nextPackets: Packet[] = [];
      for (const packet of packets) {
        const edge = edges[packet.edgeIndex];
        const from = nodes[packet.from];
        const to = nodes[packet.to];
        let speed = packet.speed;
        if (mouse.x !== null && mouse.y !== null) {
          const px = from.x + (to.x - from.x) * packet.t;
          const py = from.y + (to.y - from.y) * packet.t;
          const dist = Math.hypot(px - mouse.x, py - mouse.y);
          // Nearby particles accelerate slightly — never dramatically —
          // fading to no effect beyond ~90px.
          const proximity = Math.max(0, 1 - dist / 90);
          speed *= 1 + proximity * 0.5;
        }
        packet.t += (speed * dt) / Math.max(edge.length, 1);

        if (packet.t < 1) {
          nextPackets.push(packet);
          continue;
        }

        const arrivedNode = packet.to;
        nodes[arrivedNode].glowStart = now;
        ripples.push({ x: nodes[arrivedNode].x, y: nodes[arrivedNode].y, start: now });

        const isMerge =
          lastGlowNode === arrivedNode && now - lastGlowAt < MERGE_WINDOW_MS && Math.random() < 0.5;
        lastGlowNode = arrivedNode;
        lastGlowAt = now;

        packet.hops += 1;
        const outgoing = adjacency[arrivedNode].filter((edgeIdx) => edgeIdx !== packet.edgeIndex);
        const pool = outgoing.length > 0 ? outgoing : adjacency[arrivedNode];

        if (isMerge || packet.hops >= packet.maxHops || pool.length === 0) {
          continue;
        }

        const nextEdgeIndex = pool[Math.floor(Math.random() * pool.length)];
        const nextEdge = edges[nextEdgeIndex];
        nextPackets.push({
          edgeIndex: nextEdgeIndex,
          from: arrivedNode,
          to: otherEndpoint(nextEdge, arrivedNode),
          t: 0,
          speed: PACKET_SPEED_PX_PER_MS * (0.85 + Math.random() * 0.3),
          hops: packet.hops,
          maxHops: packet.maxHops,
        });

        if (packet.hops === 1 && Math.random() < 0.18 && packets.length + nextPackets.length < MAX_PACKETS && pool.length > 1) {
          const branchPool = pool.filter((idx) => idx !== nextEdgeIndex);
          if (branchPool.length > 0) {
            const branchEdgeIndex = branchPool[Math.floor(Math.random() * branchPool.length)];
            const branchEdge = edges[branchEdgeIndex];
            nextPackets.push({
              edgeIndex: branchEdgeIndex,
              from: arrivedNode,
              to: otherEndpoint(branchEdge, arrivedNode),
              t: 0,
              speed: PACKET_SPEED_PX_PER_MS * (0.85 + Math.random() * 0.3),
              hops: packet.hops,
              maxHops: packet.maxHops,
            });
          }
        }
      }
      packets = nextPackets;
      ripples = ripples.filter((ripple) => now - ripple.start < RIPPLE_DURATION_MS);

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, container!.clientWidth, container!.clientHeight);

      for (const orb of orbs) {
        const gradient = ctx.createRadialGradient(orb.x, orb.y, 0, orb.x, orb.y, orb.r);
        gradient.addColorStop(0, `rgba(${accent}, 0.11)`);
        gradient.addColorStop(1, `rgba(${accent}, 0)`);
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(orb.x, orb.y, orb.r, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.lineWidth = 1;
      for (const edge of edges) {
        const a = nodes[edge.a];
        const b = nodes[edge.b];
        const aGlow = a.glowStart === null ? 0 : Math.max(0, 1 - (now - a.glowStart) / GLOW_DURATION_MS);
        const bGlow = b.glowStart === null ? 0 : Math.max(0, 1 - (now - b.glowStart) / GLOW_DURATION_MS);
        const boost = Math.max(aGlow, bGlow) * 0.35;
        ctx.strokeStyle = `rgba(${accent}, ${(0.1 + boost).toFixed(3)})`;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }

      for (const ripple of ripples) {
        const elapsed = now - ripple.start;
        const progress = elapsed / RIPPLE_DURATION_MS;
        const radius = progress * RIPPLE_MAX_RADIUS;
        const opacity = 0.3 * (1 - progress);
        ctx.beginPath();
        ctx.strokeStyle = `rgba(${accent}, ${opacity.toFixed(3)})`;
        ctx.lineWidth = 1;
        ctx.arc(ripple.x, ripple.y, radius, 0, Math.PI * 2);
        ctx.stroke();
      }

      for (const node of nodes) {
        const glow = node.glowStart === null ? 0 : Math.max(0, 1 - (now - node.glowStart) / GLOW_DURATION_MS);
        const radius = node.r + glow * 1.6;
        if (glow > 0.02) {
          const haloR = radius + 8 * glow;
          const gradient = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, haloR);
          gradient.addColorStop(0, `rgba(${accent}, ${(0.5 * glow).toFixed(3)})`);
          gradient.addColorStop(1, `rgba(${accent}, 0)`);
          ctx.fillStyle = gradient;
          ctx.beginPath();
          ctx.arc(node.x, node.y, haloR, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.beginPath();
        const baseAlpha = node.isHub ? 0.45 : 0.32;
        const alpha = baseAlpha + glow * 0.5;
        ctx.fillStyle = glow > 0.02 ? `rgba(${accent}, ${Math.min(1, alpha).toFixed(3)})` : "rgba(226, 232, 240, 0.32)";
        ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
        ctx.fill();
      }

      for (const packet of packets) {
        const from = nodes[packet.from];
        const to = nodes[packet.to];
        const eased = packet.t * packet.t * (3 - 2 * packet.t);
        const x = from.x + (to.x - from.x) * eased;
        const y = from.y + (to.y - from.y) * eased;
        const haloR = 9;
        const gradient = ctx.createRadialGradient(x, y, 0, x, y, haloR);
        gradient.addColorStop(0, `rgba(${accent}, 0.9)`);
        gradient.addColorStop(0.4, `rgba(${accent}, 0.35)`);
        gradient.addColorStop(1, `rgba(${accent}, 0)`);
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(x, y, haloR, 0, Math.PI * 2);
        ctx.fill();
        ctx.beginPath();
        ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
        ctx.arc(x, y, 1.6, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    rafId = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", handleResize);
      container.removeEventListener("pointermove", handlePointerMove);
      container.removeEventListener("pointerleave", handlePointerLeave);
      document.removeEventListener("visibilitychange", handleVisibility);
      if (resizeTimer) clearTimeout(resizeTimer);
    };
  }, []);

  return (
    <div ref={containerRef} className={className} aria-hidden>
      <canvas ref={canvasRef} className="block h-full w-full" />
    </div>
  );
}
