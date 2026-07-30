import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement several browser APIs the @base-ui/react popup
// primitives (Select, Dialog, DropdownMenu, AlertDialog) rely on for
// positioning/pointer-capture — polyfilled here once, for every test,
// rather than in each individual test file.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = () => {};
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = () => {};
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
