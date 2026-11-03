import { act, render, screen } from "@testing-library/react";
import { StrictMode, useRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useMeasuredCssSize } from "./useMeasuredCssSize";

// Mock the layout/observer boundary, never the hook. Each box can resize
// without a React render, as fonts or container changes do in a browser.
class Observer {
  static instances: Observer[] = [];
  observe = vi.fn();
  disconnect = vi.fn();
  constructor(readonly notify: () => void) { Observer.instances.push(this); }
}

function Harness({ present = true, rootKey = "root", elementKey = "bar", height = 40,
  property = "--toolbar-h", ignoreZero = false }: {
  present?: boolean; rootKey?: string; elementKey?: string; height?: number;
  property?: `--${string}`; ignoreZero?: boolean;
}) {
  const rootRef = useRef<HTMLElement>(null);
  const elementRef = useRef<HTMLDivElement>(null);
  useMeasuredCssSize({ rootRef, elementRef, property, ignoreZero });
  return <main key={rootKey} ref={rootRef}>
    {present && <div key={elementKey} ref={elementRef} data-height={height}>Toolbar</div>}
  </main>;
}

const size = (root = screen.getByRole("main"), property = "--toolbar-h") => root.style.getPropertyValue(property);

beforeEach(() => {
  Observer.instances = [];
  vi.stubGlobal("ResizeObserver", Observer);
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    return { height: Number(this.dataset.height ?? 0) } as DOMRect;
  });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("useMeasuredCssSize", () => {
  it("measures before paint and responds to renders, window and container resizes", () => {
    const { rerender, unmount } = render(<Harness />);
    const root = screen.getByRole("main");
    const toolbar = screen.getByText("Toolbar");
    expect(size()).toBe("40px");
    expect(Observer.instances[0].observe).toHaveBeenCalledWith(toolbar, { box: "border-box" });
    rerender(<Harness height={60} />);
    expect(size()).toBe("60px");
    toolbar.dataset.height = "80";
    act(() => window.dispatchEvent(new Event("resize")));
    expect(size()).toBe("80px");
    toolbar.dataset.height = "100";
    act(() => Observer.instances[0].notify());
    expect(size()).toBe("100px");
    const write = vi.spyOn(root.style, "setProperty");
    act(() => Observer.instances[0].notify());
    expect(write).not.toHaveBeenCalled();
    expect(Observer.instances).toHaveLength(1);
    unmount();
    expect(size(root)).toBe("");
    expect(Observer.instances[0].disconnect).toHaveBeenCalledOnce();
    toolbar.dataset.height = "120";
    act(() => { window.dispatchEvent(new Event("resize")); Observer.instances[0].notify(); });
    expect(write).not.toHaveBeenCalled();
  });

  it("starts observing a toolbar that arrives after loading and releases removed targets", () => {
    const { rerender } = render(<Harness present={false} />);
    expect(Observer.instances).toHaveLength(0);
    rerender(<Harness />);
    expect(size()).toBe("40px");
    expect(Observer.instances).toHaveLength(1);
    rerender(<Harness elementKey="replacement" height={40} />);
    expect(Observer.instances[0].disconnect).toHaveBeenCalledOnce();
    expect(Observer.instances[1].observe).toHaveBeenCalledWith(screen.getByText("Toolbar"), { box: "border-box" });
    expect(size()).toBe("40px");
    rerender(<Harness present={false} />);
    expect(Observer.instances[1].disconnect).toHaveBeenCalledOnce();
    expect(size()).toBe("");
  });

  it("remeasures a replaced root even at the same height, and restores old property names", () => {
    const { rerender } = render(<Harness />);
    const oldRoot = screen.getByRole("main");
    rerender(<Harness rootKey="replacement" />);
    expect(size(oldRoot)).toBe("");
    expect(size()).toBe("40px");
    rerender(<Harness rootKey="replacement" property="--other-h" />);
    expect(size()).toBe("");
    expect(size(screen.getByRole("main"), "--other-h")).toBe("40px");
  });

  it("works without ResizeObserver and keeps zero-height policy caller-owned", () => {
    vi.stubGlobal("ResizeObserver", undefined);
    const { rerender } = render(<Harness height={0} ignoreZero />);
    expect(size()).toBe("");
    rerender(<Harness height={50} ignoreZero />);
    expect(size()).toBe("50px");
    screen.getByText("Toolbar").dataset.height = "70";
    act(() => window.dispatchEvent(new Event("resize")));
    expect(size()).toBe("70px");
    rerender(<Harness height={0} ignoreZero />);
    expect(size()).toBe("70px");
    rerender(<Harness height={0} />);
    expect(size()).toBe("0px");
  });

  it("restores the prior inline value and priority, but never a later external write", () => {
    const { rerender, unmount } = render(<Harness present={false} />);
    const root = screen.getByRole("main");
    root.style.setProperty("--toolbar-h", "8px", "important");
    rerender(<Harness />);
    expect(size()).toBe("40px");
    rerender(<Harness present={false} />);
    expect(size()).toBe("8px");
    expect(root.style.getPropertyPriority("--toolbar-h")).toBe("important");
    rerender(<Harness />);
    root.style.setProperty("--toolbar-h", "external");
    unmount();
    expect(size(root)).toBe("external");
  });

  it("StrictMode leaves only one live observer and no listener after cleanup", () => {
    const { unmount } = render(<StrictMode><Harness /></StrictMode>);
    expect(size()).toBe("40px");
    expect(Observer.instances.filter((observer) => observer.disconnect.mock.calls.length === 0)).toHaveLength(1);
    const root = screen.getByRole("main");
    unmount();
    expect(Observer.instances.every((observer) => observer.disconnect.mock.calls.length === 1)).toBe(true);
    expect(size(root)).toBe("");
  });
});
