import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

// Merge Tailwind class names with conflict resolution
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Format fen to yuan display string
export function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}
