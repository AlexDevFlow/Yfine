import { useEffect, useRef, useState } from "react";
import { SlotText, type SlotTextProps } from "slot-text/react";
import type { SlotOptions } from "slot-text";

/** Track the OS "reduce motion" preference so rolls can collapse to a swap. */
function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

// slot-text animates via the Web Animations API, so the global
// prefers-reduced-motion CSS rule can't reach it — zero the timing here instead.
const STILL: SlotOptions = { duration: 0, stagger: 0, exitOffset: 0 };

/** SlotText that collapses to an instant swap when "reduce motion" is on. */
export function Slot({ options, ...props }: SlotTextProps) {
  const reduced = usePrefersReducedMotion();
  return <SlotText {...props} options={reduced ? { ...options, ...STILL } : options} />;
}

interface SlotMoneyProps {
  /** Numeric basis for the roll direction (rolls up when it grows, down when it shrinks). */
  value: number;
  /** Pre-formatted text to display (e.g. "€1,234.56"). */
  text: string;
  className?: string;
  options?: SlotOptions;
}

/** Animated number/money label: rolls up on an increase, down on a decrease. */
export function SlotMoney({ value, text, className, options }: SlotMoneyProps) {
  const prevRef = useRef(value);
  const direction = value > prevRef.current ? "up" : value < prevRef.current ? "down" : options?.direction ?? "down";
  useEffect(() => {
    prevRef.current = value;
  }, [value]);
  return <Slot className={className} text={text} options={{ ...options, direction }} />;
}
