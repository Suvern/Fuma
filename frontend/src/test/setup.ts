import { vi } from "vitest";

// jsdom does not implement layout APIs used by Semi's popovers and text measurement.
if (typeof window !== "undefined") {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
    value: () => ({
      measureText: (text: string) => ({ width: text.length * 8 }),
      fillText() {},
      clearRect() {},
      fillRect() {},
      getImageData: () => ({ data: [] }),
      setTransform() {},
      drawImage() {},
      save() {},
      restore() {},
      scale() {},
      translate() {},
      rotate() {},
      beginPath() {},
      closePath() {},
      stroke() {},
      fill() {},
      arc() {},
      lineTo() {},
      moveTo() {},
    }),
  });
  HTMLElement.prototype.scrollIntoView = () => {};
  Range.prototype.getBoundingClientRect = () => new DOMRect();
}
