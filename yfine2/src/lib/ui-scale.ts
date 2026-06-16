const SCALE_MAP: Record<string, string> = {
  small: "15px",
  normal: "16px",
  large: "18px",
  xlarge: "20px",
};

/** Apply an interface-size preference by setting the root font size. */
export function applyUiScale(scale: string): void {
  document.documentElement.style.fontSize = SCALE_MAP[scale] ?? "16px";
}
