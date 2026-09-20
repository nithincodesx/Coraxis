"use client";

/**
 * Particle network backdrop.
 *
 * A drifting field of nodes that link to their neighbours. Chosen over generic
 * decoration because nodes forming connections is what the product actually is.
 * Restraint is the point: low count, long link distance, and opacity that stays
 * well under any text.
 *
 * `enabled` freezes the field rather than hiding it — the user turned motion
 * off, not the backdrop — and `prefers-reduced-motion` is treated the same way.
 *
 * Other details that matter:
 * * Colours are read from the theme tokens and re-read when `data-theme`
 *   changes, so light mode gets ink links instead of invisible white ones.
 * * Sized in device pixels (DPR capped at 2) so it stays crisp on retina.
 * * The RAF is cancelled on unmount, so navigating away leaks no loop.
 */

import { useEffect, useRef } from "react";

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

/** Deliberately low: density reads as noise, sparseness reads as intent. */
const DEFAULT_COUNT = 52;
const MAX_LINK_DISTANCE = 150;
const SPEED = 0.16;

function readToken(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** Parse `#rrggbb` or `rgba(...)` into an `r, g, b` triple for templating. */
function toRgbTriple(value: string): string {
  const hex = value.match(/^#([0-9a-f]{6})$/i);
  if (hex) {
    const n = parseInt(hex[1], 16);
    return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
  }
  const rgb = value.match(/rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i);
  if (rgb) return `${Math.round(+rgb[1])}, ${Math.round(+rgb[2])}, ${Math.round(+rgb[3])}`;
  return "255, 255, 255";
}

interface Props {
  /** When false, one static frame is drawn and the loop never starts. */
  enabled?: boolean;
  /** Particle count. Lower it for a backdrop behind dense content. */
  count?: number;
}

export default function HeroBackdrop({ enabled = true, count = DEFAULT_COUNT }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let frame = 0;
    let running = false;
    let particles: Particle[] = [];
    let width = 0;
    let height = 0;
    let rgb = toRgbTriple(readToken("--text", "#f2f5f3"));

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    /** Motion runs only when both the user's setting and the OS allow it. */
    const shouldAnimate = () => enabled && !reducedMotion;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = rect.width;
      height = rect.height;
      canvas.width = Math.max(1, Math.floor(width * dpr));
      canvas.height = Math.max(1, Math.floor(height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // Re-seed so density stays constant across resizes rather than bunching
      // every particle into the top-left of a larger canvas.
      particles = Array.from({ length: count }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * SPEED,
        vy: (Math.random() - 0.5) * SPEED,
      }));
    };

    const draw = (advance: boolean) => {
      ctx.clearRect(0, 0, width, height);

      if (advance) {
        for (const p of particles) {
          p.x += p.vx;
          p.y += p.vy;
          // Wrap rather than bounce: bouncing visibly clusters at the edges.
          if (p.x < -20) p.x = width + 20;
          if (p.x > width + 20) p.x = -20;
          if (p.y < -20) p.y = height + 20;
          if (p.y > height + 20) p.y = -20;
        }
      }

      // Links first, so nodes sit on top of the web.
      for (let i = 0; i < particles.length; i += 1) {
        for (let j = i + 1; j < particles.length; j += 1) {
          const a = particles[i];
          const b = particles[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const distance = Math.hypot(dx, dy);
          if (distance > MAX_LINK_DISTANCE) continue;

          const strength = 1 - distance / MAX_LINK_DISTANCE;
          ctx.strokeStyle = `rgba(${rgb}, ${(strength * 0.16).toFixed(3)})`;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }

      for (const p of particles) {
        ctx.fillStyle = `rgba(${rgb}, 0.34)`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 1.3, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    const loop = () => {
      if (!shouldAnimate()) {
        running = false;
        return;
      }
      draw(true);
      frame = window.requestAnimationFrame(loop);
    };

    const start = () => {
      window.cancelAnimationFrame(frame);
      if (shouldAnimate()) {
        if (!running) {
          running = true;
          frame = window.requestAnimationFrame(loop);
        }
      } else {
        running = false;
        draw(false);
      }
    };

    resize();
    start();

    const onResize = () => {
      resize();
      if (!shouldAnimate()) draw(false);
    };
    window.addEventListener("resize", onResize);

    // Re-read the palette when the theme flips. The animation setting does not
    // need handling here: `enabled` is a dependency, so the effect restarts.
    const observer = new MutationObserver(() => {
      rgb = toRgbTriple(readToken("--text", "#f2f5f3"));
      if (!shouldAnimate()) draw(false);
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });

    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
      observer.disconnect();
    };
  }, [count, enabled]);

  return <canvas ref={canvasRef} aria-hidden className="sb-canvas" />;
}
