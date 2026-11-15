import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Memory } from "./lib/api";

type GraphNode = {
  id: string;
  label: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  linkCount: number;
};

type GraphEdge = {
  source: string;
  target: string;
};

const NODE_RADIUS_BASE = 18;
const NODE_RADIUS_SCALE = 3;
const REPULSION = 4000;
const ATTRACTION = 0.008;
const EDGE_LENGTH = 140;
const DAMPING = 0.88;
const CENTER_PULL = 0.002;
const VELOCITY_THRESHOLD = 0.15;
const SLEEP_AFTER_TICKS = 60;
const THETA = 0.8;

// --- Barnes-Hut Quadtree ---

type QuadBody = { x: number; y: number; mass: number };

type QuadNode = {
  cx: number;
  cy: number;
  mass: number;
  body: QuadBody | null;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  children: (QuadNode | null)[];
};

function createQuadNode(x0: number, y0: number, x1: number, y1: number): QuadNode {
  return { cx: 0, cy: 0, mass: 0, body: null, x0, y0, x1, y1, children: [null, null, null, null] };
}

function quadInsert(node: QuadNode, body: QuadBody): void {
  if (node.mass === 0) {
    node.body = body;
    node.mass = body.mass;
    node.cx = body.x;
    node.cy = body.y;
    return;
  }

  const midX = (node.x0 + node.x1) / 2;
  const midY = (node.y0 + node.y1) / 2;

  if (node.body) {
    const existing = node.body;
    node.body = null;
    insertIntoChild(node, existing, midX, midY);
  }

  insertIntoChild(node, body, midX, midY);

  node.cx = (node.cx * node.mass + body.x * body.mass) / (node.mass + body.mass);
  node.cy = (node.cy * node.mass + body.y * body.mass) / (node.mass + body.mass);
  node.mass += body.mass;
}

function insertIntoChild(node: QuadNode, body: QuadBody, midX: number, midY: number): void {
  const idx = (body.x > midX ? 1 : 0) + (body.y > midY ? 2 : 0);
  if (!node.children[idx]) {
    const x0 = idx & 1 ? midX : node.x0;
    const y0 = idx & 2 ? midY : node.y0;
    const x1 = idx & 1 ? node.x1 : midX;
    const y1 = idx & 2 ? node.y1 : midY;
    node.children[idx] = createQuadNode(x0, y0, x1, y1);
  }
  quadInsert(node.children[idx]!, body);
}

function quadForce(node: QuadNode, body: QuadBody, theta: number, fx: { x: number; y: number }): void {
  if (node.mass === 0) return;

  let dx = node.cx - body.x;
  let dy = node.cy - body.y;
  const distSq = dx * dx + dy * dy;

  if (distSq < 0.01) return;

  const size = node.x1 - node.x0;

  if (node.body || (size * size) / distSq < theta * theta) {
    const dist = Math.sqrt(distSq);
    const force = REPULSION * node.mass / distSq;
    fx.x -= (dx / dist) * force;
    fx.y -= (dy / dist) * force;
    return;
  }

  for (const child of node.children) {
    if (child) quadForce(child, body, theta, fx);
  }
}

function buildQuadTree(nodes: GraphNode[]): QuadNode {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const n of nodes) {
    if (n.x < minX) minX = n.x;
    if (n.y < minY) minY = n.y;
    if (n.x > maxX) maxX = n.x;
    if (n.y > maxY) maxY = n.y;
  }
  const pad = 50;
  const root = createQuadNode(minX - pad, minY - pad, maxX + pad, maxY + pad);
  for (const n of nodes) {
    quadInsert(root, { x: n.x, y: n.y, mass: 1 });
  }
  return root;
}

// --- Graph building ---

function buildGraph(notes: Memory[], radiusBase: number): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const noteIds = new Set(notes.map((n) => n.id));
  const edges: GraphEdge[] = [];
  const linkCounts = new Map<string, number>();

  for (const note of notes) {
    for (const targetId of note.linkedMemoryIds) {
      if (noteIds.has(targetId) && targetId !== note.id) {
        edges.push({ source: note.id, target: targetId });
        linkCounts.set(note.id, (linkCounts.get(note.id) ?? 0) + 1);
        linkCounts.set(targetId, (linkCounts.get(targetId) ?? 0) + 1);
      }
    }
  }

  const angle = (2 * Math.PI) / Math.max(notes.length, 1);
  const spread = Math.min(300, notes.length * 30);
  const rScale = radiusBase < NODE_RADIUS_BASE ? 1 : NODE_RADIUS_SCALE;

  const nodes: GraphNode[] = notes.map((note, i) => {
    const count = linkCounts.get(note.id) ?? 0;
    return {
      id: note.id,
      label: note.title,
      x: Math.cos(angle * i) * spread + (Math.random() - 0.5) * 40,
      y: Math.sin(angle * i) * spread + (Math.random() - 0.5) * 40,
      vx: 0,
      vy: 0,
      radius: radiusBase + count * rScale,
      linkCount: count,
    };
  });

  return { nodes, edges };
}

function buildLinkedSet(edges: GraphEdge[], nodeId: string | null): Set<string> {
  const set = new Set<string>();
  if (!nodeId) return set;
  for (const e of edges) {
    if (e.source === nodeId) set.add(e.target);
    else if (e.target === nodeId) set.add(e.source);
  }
  return set;
}

function buildAdjacency(notes: Memory[]): Map<string, Set<string>> {
  const noteIds = new Set(notes.map((n) => n.id));
  const adj = new Map<string, Set<string>>();
  for (const note of notes) {
    if (!adj.has(note.id)) adj.set(note.id, new Set());
    for (const targetId of note.linkedMemoryIds) {
      if (noteIds.has(targetId) && targetId !== note.id) {
        adj.get(note.id)!.add(targetId);
        if (!adj.has(targetId)) adj.set(targetId, new Set());
        adj.get(targetId)!.add(note.id);
      }
    }
  }
  return adj;
}

function findFromExpanded(notes: Memory[], expandedIds: Set<string>): Memory[] {
  if (expandedIds.size === 0) return [];
  const adj = buildAdjacency(notes);
  const visible = new Set<string>(expandedIds);
  for (const id of expandedIds) {
    const neighbors = adj.get(id);
    if (neighbors) {
      for (const nid of neighbors) visible.add(nid);
    }
  }
  return notes.filter((n) => visible.has(n.id));
}

export function NoteGraph({
  notes,
  selectedNoteId,
  onSelectNote,
}: {
  notes: Memory[];
  selectedNoteId: string | null;
  onSelectNote: (id: string) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const nodesRef = useRef<GraphNode[]>([]);
  const edgesRef = useRef<GraphEdge[]>([]);
  const dragRef = useRef<{ nodeId: string; offsetX: number; offsetY: number } | null>(null);
  const panRef = useRef({ x: 0, y: 0, dragging: false, startX: 0, startY: 0, panStartX: 0, panStartY: 0 });
  const scaleRef = useRef(1);
  const hoveredRef = useRef<string | null>(null);
  const animRef = useRef(0);
  const sleepingRef = useRef(false);
  const settledTicksRef = useRef(0);
  const needsRedrawRef = useRef(false);
  const lastClickRef = useRef<{ nodeId: string; time: number } | null>(null);

  const [, forceRender] = useState(0);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() =>
    selectedNoteId ? new Set([selectedNoteId]) : new Set()
  );
  const graphClickRef = useRef(false);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; label: string; links: number } | null>(null);

  const wake = useCallback(() => {
    if (sleepingRef.current) {
      sleepingRef.current = false;
      settledTicksRef.current = 0;
      forceRender((n) => n + 1);
    }
    needsRedrawRef.current = true;
  }, []);

  const expandNode = useCallback((nodeId: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      next.add(nodeId);
      return next;
    });
  }, []);

  const resetGraph = useCallback(() => {
    setExpandedIds(new Set());
  }, []);

  const fitToView = useCallback(() => {
    const nodes = nodesRef.current;
    const canvas = canvasRef.current;
    if (!canvas || nodes.length === 0) return;
    const dpr = devicePixelRatio;
    const w = canvas.width / dpr;
    const h = canvas.height / dpr;

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of nodes) {
      const r = n.radius + 20;
      if (n.x - r < minX) minX = n.x - r;
      if (n.y - r < minY) minY = n.y - r;
      if (n.x + r > maxX) maxX = n.x + r;
      if (n.y + r > maxY) maxY = n.y + r;
    }

    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;
    const scale = Math.min(w / rangeX, h / rangeY) * 0.85;
    scaleRef.current = Math.max(0.2, Math.min(4, scale));
    panRef.current.x = -(minX + rangeX / 2);
    panRef.current.y = -(minY + rangeY / 2);
    needsRedrawRef.current = true;
    forceRender((n) => n + 1);
  }, []);

  const centerOnSelected = useCallback(() => {
    if (!selectedNoteId) return;
    const node = nodesRef.current.find((n) => n.id === selectedNoteId);
    if (!node) return;
    panRef.current.x = -node.x;
    panRef.current.y = -node.y;
    needsRedrawRef.current = true;
    forceRender((n) => n + 1);
  }, [selectedNoteId]);

  const zoomIn = useCallback(() => {
    scaleRef.current = Math.min(4, scaleRef.current * 1.3);
    needsRedrawRef.current = true;
    forceRender((n) => n + 1);
  }, []);

  const zoomOut = useCallback(() => {
    scaleRef.current = Math.max(0.2, scaleRef.current / 1.3);
    needsRedrawRef.current = true;
    forceRender((n) => n + 1);
  }, []);

  const visibleNotes = useMemo(() => {
    const active = notes.filter((n) => !n.deletedAt);
    // Empty selection = show the whole graph; otherwise focus the expanded neighborhood.
    return expandedIds.size === 0 ? active : findFromExpanded(active, expandedIds);
  }, [notes, expandedIds]);

  useEffect(() => {
    const count = visibleNotes.length;
    const radiusBase = count > 500 ? 8 : count > 200 ? 12 : NODE_RADIUS_BASE;
    const { nodes, edges } = buildGraph(visibleNotes, radiusBase);
    nodesRef.current = nodes;
    edgesRef.current = edges;
    panRef.current.x = 0;
    panRef.current.y = 0;
    scaleRef.current = 1;
    sleepingRef.current = false;
    settledTicksRef.current = 0;
    forceRender((n) => n + 1);
  }, [visibleNotes]);

  const toCanvas = useCallback((x: number, y: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const pan = panRef.current;
    const scale = scaleRef.current;
    return {
      x: (x - canvas.width / 2 / devicePixelRatio - pan.x) / scale,
      y: (y - canvas.height / 2 / devicePixelRatio - pan.y) / scale,
    };
  }, []);

  const findNode = useCallback((mx: number, my: number) => {
    const pt = toCanvas(mx, my);
    for (let i = nodesRef.current.length - 1; i >= 0; i--) {
      const n = nodesRef.current[i];
      const dx = pt.x - n.x;
      const dy = pt.y - n.y;
      if (dx * dx + dy * dy <= n.radius * n.radius) return n;
    }
    return null;
  }, [toCanvas]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const handleDown = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const node = findNode(mx, my);
      if (node) {
        const pt = toCanvas(mx, my);
        dragRef.current = { nodeId: node.id, offsetX: pt.x - node.x, offsetY: pt.y - node.y };
        wake();
      } else {
        panRef.current.dragging = true;
        panRef.current.startX = e.clientX;
        panRef.current.startY = e.clientY;
        panRef.current.panStartX = panRef.current.x;
        panRef.current.panStartY = panRef.current.y;
      }
    };

    const handleMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      if (dragRef.current) {
        const pt = toCanvas(mx, my);
        const node = nodesRef.current.find((n) => n.id === dragRef.current!.nodeId);
        if (node) {
          node.x = pt.x - dragRef.current.offsetX;
          node.y = pt.y - dragRef.current.offsetY;
          node.vx = 0;
          node.vy = 0;
        }
        wake();
        setTooltip(null);
      } else if (panRef.current.dragging) {
        panRef.current.x = panRef.current.panStartX + (e.clientX - panRef.current.startX) / scaleRef.current;
        panRef.current.y = panRef.current.panStartY + (e.clientY - panRef.current.startY) / scaleRef.current;
        needsRedrawRef.current = true;
        setTooltip(null);
      } else {
        const node = findNode(mx, my);
        const prev = hoveredRef.current;
        hoveredRef.current = node?.id ?? null;
        canvas.style.cursor = node ? "pointer" : "grab";
        if (prev !== hoveredRef.current) needsRedrawRef.current = true;

        if (node) {
          setTooltip({ x: mx + 12, y: my - 8, label: node.label, links: node.linkCount });
        } else {
          setTooltip(null);
        }
      }
    };

    const handleUp = () => {
      if (dragRef.current) {
        const node = nodesRef.current.find((n) => n.id === dragRef.current!.nodeId);
        if (node) {
          const now = Date.now();
          const last = lastClickRef.current;
          if (last && last.nodeId === node.id && now - last.time < 350) {
            expandNode(node.id);
            lastClickRef.current = null;
          } else {
            lastClickRef.current = { nodeId: node.id, time: now };
            graphClickRef.current = true;
            onSelectNote(node.id);
          }
        }
        dragRef.current = null;
      }
      panRef.current.dragging = false;
    };

    const handleLeave = () => {
      if (dragRef.current) dragRef.current = null;
      panRef.current.dragging = false;
      setTooltip(null);
      hoveredRef.current = null;
      needsRedrawRef.current = true;
    };

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      const factor = e.deltaY > 0 ? 0.92 : 1.08;
      scaleRef.current = Math.max(0.2, Math.min(4, scaleRef.current * factor));
      needsRedrawRef.current = true;
    };

    canvas.addEventListener("mousedown", handleDown);
    canvas.addEventListener("mousemove", handleMove);
    canvas.addEventListener("mouseup", handleUp);
    canvas.addEventListener("mouseleave", handleLeave);
    canvas.addEventListener("wheel", handleWheel, { passive: false });
    return () => {
      canvas.removeEventListener("mousedown", handleDown);
      canvas.removeEventListener("mousemove", handleMove);
      canvas.removeEventListener("mouseup", handleUp);
      canvas.removeEventListener("mouseleave", handleLeave);
      canvas.removeEventListener("wheel", handleWheel);
    };
  }, [findNode, toCanvas, onSelectNote, wake, expandNode]);

  // Keyboard shortcuts
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      switch (e.key) {
        case "=":
        case "+":
          e.preventDefault();
          zoomIn();
          break;
        case "-":
          e.preventDefault();
          zoomOut();
          break;
        case "f":
          e.preventDefault();
          fitToView();
          break;
        case "c":
          e.preventDefault();
          centerOnSelected();
          break;
        case "e":
          e.preventDefault();
          if (selectedNoteId) expandNode(selectedNoteId);
          break;
        case "r":
          e.preventDefault();
          resetGraph();
          break;
      }
    };

    container.addEventListener("keydown", handleKey);
    return () => container.removeEventListener("keydown", handleKey);
  }, [zoomIn, zoomOut, fitToView, centerOnSelected, expandNode, resetGraph, selectedNoteId]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const resize = () => {
      const dpr = devicePixelRatio;
      canvas.width = container.clientWidth * dpr;
      canvas.height = container.clientHeight * dpr;
      canvas.style.width = `${container.clientWidth}px`;
      canvas.style.height = `${container.clientHeight}px`;
      needsRedrawRef.current = true;
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let running = true;

    const draw = () => {
      const nodes = nodesRef.current;
      const edges = edgesRef.current;
      const dpr = devicePixelRatio;
      const w = canvas.width / dpr;
      const h = canvas.height / dpr;
      const scale = scaleRef.current;
      const pan = panRef.current;
      const nodeMap = new Map(nodes.map((n) => [n.id, n]));
      const currentLinkedSet = buildLinkedSet(edges, selectedNoteId);

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.save();
      ctx.translate(w / 2 + pan.x * scale, h / 2 + pan.y * scale);
      ctx.scale(scale, scale);

      for (const edge of edges) {
        const a = nodeMap.get(edge.source);
        const b = nodeMap.get(edge.target);
        if (!a || !b) continue;
        const isHighlighted =
          selectedNoteId === a.id || selectedNoteId === b.id ||
          hoveredRef.current === a.id || hoveredRef.current === b.id;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = isHighlighted ? "rgba(79,110,247,0.5)" : "rgba(0,0,0,0.08)";
        ctx.lineWidth = isHighlighted ? 2 : 1;
        ctx.stroke();
      }

      for (const node of nodes) {
        const isSelected = node.id === selectedNoteId;
        const isHovered = node.id === hoveredRef.current;
        const isLinked = currentLinkedSet.has(node.id);

        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius, 0, 2 * Math.PI);

        if (isSelected) {
          ctx.fillStyle = "#4f6ef7";
        } else if (isLinked) {
          ctx.fillStyle = "#818cf8";
        } else if (isHovered) {
          ctx.fillStyle = "#6b7280";
        } else if (node.linkCount === 0) {
          ctx.fillStyle = "#d1d5db";
        } else {
          ctx.fillStyle = "#9ca3af";
        }
        ctx.fill();

        if (isSelected || isHovered) {
          ctx.strokeStyle = isSelected ? "#4f6ef7" : "#6b7280";
          ctx.lineWidth = 2;
          ctx.stroke();
        }

        const showLabel =
          isSelected || isHovered
            ? true
            : scale >= 1.0
              ? true
              : scale >= 0.6
                ? isLinked
                : false;

        if (showLabel) {
          const fontSize = Math.max(10, Math.min(13, 10 + node.linkCount));
          ctx.font = `${isSelected || isHovered ? 600 : 500} ${fontSize}px Inter, system-ui, sans-serif`;
          ctx.textAlign = "center";
          ctx.fillStyle = isSelected ? "#1a1a2e" : isHovered ? "#374151" : "#6b7280";
          ctx.fillText(
            node.label.length > 22 ? node.label.slice(0, 20) + "..." : node.label,
            node.x,
            node.y + node.radius + fontSize + 4
          );
        }
      }

      ctx.restore();
    };

    const tick = () => {
      if (!running) return;

      if (sleepingRef.current) {
        if (needsRedrawRef.current) {
          needsRedrawRef.current = false;
          draw();
        }
        animRef.current = requestAnimationFrame(tick);
        return;
      }

      const nodes = nodesRef.current;
      const edges = edgesRef.current;

      if (nodes.length > 1) {
        const tree = buildQuadTree(nodes);
        const forceAccum = { x: 0, y: 0 };

        for (const node of nodes) {
          forceAccum.x = 0;
          forceAccum.y = 0;
          quadForce(tree, { x: node.x, y: node.y, mass: 1 }, THETA, forceAccum);
          node.vx += forceAccum.x;
          node.vy += forceAccum.y;
          node.vx -= node.x * CENTER_PULL;
          node.vy -= node.y * CENTER_PULL;
        }
      } else if (nodes.length === 1) {
        nodes[0].vx -= nodes[0].x * CENTER_PULL;
        nodes[0].vy -= nodes[0].y * CENTER_PULL;
      }

      const nodeMap = new Map(nodes.map((n) => [n.id, n]));
      for (const edge of edges) {
        const a = nodeMap.get(edge.source);
        const b = nodeMap.get(edge.target);
        if (!a || !b) continue;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = (dist - EDGE_LENGTH) * ATTRACTION;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }

      let totalKE = 0;
      for (const node of nodes) {
        if (dragRef.current?.nodeId === node.id) continue;
        node.vx *= DAMPING;
        node.vy *= DAMPING;
        node.x += node.vx;
        node.y += node.vy;
        totalKE += node.vx * node.vx + node.vy * node.vy;
      }

      if (totalKE < VELOCITY_THRESHOLD * nodes.length) {
        settledTicksRef.current++;
        if (settledTicksRef.current >= SLEEP_AFTER_TICKS) {
          sleepingRef.current = true;
        }
      } else {
        settledTicksRef.current = 0;
      }

      draw();
      animRef.current = requestAnimationFrame(tick);
    };

    animRef.current = requestAnimationFrame(tick);
    return () => {
      running = false;
      cancelAnimationFrame(animRef.current);
    };
  }, [selectedNoteId]);

  useEffect(() => {
    if (graphClickRef.current) {
      graphClickRef.current = false;
    } else if (selectedNoteId) {
      setExpandedIds(new Set([selectedNoteId]));
    }
    needsRedrawRef.current = true;
  }, [selectedNoteId]);

  return (
    <div className="note-graph-container" ref={containerRef} tabIndex={0}>
      <canvas ref={canvasRef} className="note-graph-canvas" />

      {tooltip && (
        <div className="graph-tooltip" style={{ left: tooltip.x, top: tooltip.y }}>
          <strong>{tooltip.label}</strong>
          <span>{tooltip.links} connection{tooltip.links !== 1 ? "s" : ""}</span>
          <span className="graph-tooltip-hint">Double-click to expand</span>
        </div>
      )}

      <div className="graph-toolbar">
        <span className="graph-toolbar-count">{visibleNotes.length}</span>

        <div className="graph-toolbar-sep" />

        <button type="button" className="graph-toolbar-btn" onClick={zoomIn} title="Zoom in (+)">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="7" fill="none" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
            <line x1="11" y1="8" x2="11" y2="14" />
            <line x1="8" y1="11" x2="14" y2="11" />
          </svg>
        </button>
        <button type="button" className="graph-toolbar-btn" onClick={zoomOut} title="Zoom out (-)">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="7" fill="none" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
            <line x1="8" y1="11" x2="14" y2="11" />
          </svg>
        </button>
        <button type="button" className="graph-toolbar-btn" onClick={fitToView} title="Fit to view (F)">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 3h6v6" />
            <path d="M9 21H3v-6" />
            <path d="M21 3l-7 7" />
            <path d="M3 21l7-7" />
          </svg>
        </button>
        <button type="button" className="graph-toolbar-btn" onClick={centerOnSelected} title="Center on selected (C)">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" fill="none" />
            <line x1="12" y1="2" x2="12" y2="6" />
            <line x1="12" y1="18" x2="12" y2="22" />
            <line x1="2" y1="12" x2="6" y2="12" />
            <line x1="18" y1="12" x2="22" y2="12" />
          </svg>
        </button>

        <div className="graph-toolbar-sep" />

        <button
          type="button"
          className="graph-toolbar-btn"
          onClick={() => { if (selectedNoteId) expandNode(selectedNoteId); }}
          title="Expand selected (E)"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" fill="none" />
            <circle cx="4" cy="5" r="2" fill="none" />
            <circle cx="20" cy="5" r="2" fill="none" />
            <circle cx="4" cy="19" r="2" fill="none" />
            <circle cx="20" cy="19" r="2" fill="none" />
            <line x1="9.5" y1="10" x2="5.5" y2="7" />
            <line x1="14.5" y1="10" x2="18.5" y2="7" />
            <line x1="9.5" y1="14" x2="5.5" y2="17" />
            <line x1="14.5" y1="14" x2="18.5" y2="17" />
          </svg>
        </button>
        {expandedIds.size > 0 && (
          <button type="button" className="graph-toolbar-btn" onClick={resetGraph} title="Reset graph (R)">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 12a9 9 0 1 1 3 6.7" />
              <polyline points="3 22 3 16 9 16" fill="none" />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}
