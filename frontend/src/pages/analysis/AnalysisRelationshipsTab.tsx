import { useState, useMemo, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  BookMarked,
  Check,
  CheckCircle2,
  ChevronRight,
  Columns,
  Compass,
  ExternalLink,
  Eye,
  FileCheck2,
  FileText,
  FileWarning,
  GitBranch,
  Globe,
  HelpCircle,
  History,
  Info,
  Layers,
  Maximize2,
  Minus,
  Plus,
  RefreshCw,
  Replace,
  RotateCcw,
  Scale,
  ScrollText,
  Search,
  Share2,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  X,
  Zap,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { useRouter } from '@/router';
import {
  getRelationshipsByAnalysisId,
  getStandardById,
  standards,
  statusConfig,
  relationships as allRelationships,
} from '@/data/mockData';
import type {
  Standard,
  StandardRelationship,
  StandardRelationshipRole,
  StandardStatus,
} from '@/data/types';
import { StandardComparisonModal } from '@/components/standards/StandardComparisonModal';

interface Props {
  analysis?: any;
  analysisId?: string;
  isReal?: boolean;
}

type FilterType =
  | 'all'
  | 'primary'
  | 'normative'
  | 'testing'
  | 'safety'
  | 'installation'
  | 'equivalent'
  | 'supersedes';

interface GraphNode {
  id: string;
  standard: Standard;
  x: number;
  y: number;
  isPrimary: boolean;
  role: StandardRelationshipRole | 'equivalent' | 'supersedes';
}

export function AnalysisRelationshipsTab({ analysis, analysisId, isReal = false }: Props) {
  const { navigate } = useRouter();
  const sourceAnalysisId = analysis?.id || analysisId;
  let standardDirectory = [...standards];
  
  const localGetStandardById = (id) => standardDirectory.find(s => s.id === id) || getStandardById(id);

  let rels = getRelationshipsByAnalysisId(sourceAnalysisId);
  let primaryStd = localGetStandardById('std-10322') || standards[0];
  
  if (analysis?.standards_intelligence?.length > 0) {
    standardDirectory = analysis.standards_intelligence;
    primaryStd = standardDirectory[0];
    rels = standardDirectory.slice(1).map((std, i) => ({
      id: `rel-${i}`,
      fromStandardId: primaryStd.id,
      toStandardId: std.id,
      role: i % 2 === 0 ? 'normative' : (i % 3 === 0 ? 'testing' : 'safety'),
      isMandatory: std.isMandatory || false,
      description: `Automatically mapped reference from ${primaryStd.standardCode}`
    }));
  }



  const [activeFilter, setActiveFilter] = useState<FilterType>('all');
  const [zoomLevel, setZoomLevel] = useState<number>(1);
  const [panOffset, setPanOffset] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [isCompareModalOpen, setIsCompareModalOpen] = useState<boolean>(false);
  const containerRef = useRef<HTMLDivElement>(null);


  const relsForNodes = useMemo(() => {
    if (activeFilter === 'all' || activeFilter === 'primary') return rels;
    return rels.filter(r => r.role === activeFilter);
  }, [rels, activeFilter]);


  // Active selected node in inspector
  const [selectedNodeId, setSelectedNodeId] = useState<string>(primaryStd.id);

  // Graph nodes configuration
  // Width: 840, Height: 520. Center: (420, 260)
  const graphNodes: GraphNode[] = useMemo(() => {
    const nodes: GraphNode[] = [
      {
        id: primaryStd.id || 'primary',
        standard: primaryStd,
        x: 420,
        y: 250,
        isPrimary: true,
        role: 'primary',
      }
    ];

    const radius = 180;
    const center = { x: 420, y: 250 };
    
    relsForNodes.forEach((r, i) => {
        const std = localGetStandardById(r.toStandardId);
        if (std) {
            const angle = (i * (Math.PI * 2)) / relsForNodes.length;
            nodes.push({
                id: r.toStandardId,
                standard: std,
                x: center.x + radius * Math.cos(angle),
                y: center.y + radius * Math.sin(angle),
                isPrimary: false,
                role: r.role,
            });
        }
    });

    return nodes;
  }, [primaryStd, relsForNodes]);


  // Selected standard details
  const selectedNode = graphNodes.find((n) => n.id === selectedNodeId) || graphNodes[0];
  const selectedStandard = selectedNode?.standard;

  // Active relationship linking selected node to primary
  const selectedRelationship = useMemo(() => {
    if (!selectedNode || selectedNode.isPrimary) return null;
    return rels.find(
      (r) =>
        (r.fromStandardId === selectedNode.id && r.toStandardId === primaryStd.id) ||
        (r.toStandardId === selectedNode.id && r.fromStandardId === primaryStd.id)
    );
  }, [selectedNode, primaryStd.id, rels]);

  // Filtered nodes and edges
  const visibleNodes = useMemo(() => {
    if (activeFilter === 'all') return graphNodes;
    if (activeFilter === 'primary') return graphNodes.filter((n) => n.isPrimary);
    return graphNodes.filter((n) => n.isPrimary || n.role === activeFilter);
  }, [graphNodes, activeFilter]);

  const visibleNodeIds = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes]);

  const visibleRels = useMemo(() => {
    return rels.filter(
      (r) => visibleNodeIds.has(r.fromStandardId) && visibleNodeIds.has(r.toStandardId)
    );
  }, [rels, visibleNodeIds]);

  // Counts for relationship summary strip
  const relCounts = useMemo(() => {
    return {
      primary: 1,
      normative: rels.filter((r) => r.role === 'normative').length,
      testing: rels.filter((r) => r.role === 'testing').length,
      safety: rels.filter((r) => r.role === 'safety').length,
      installation: rels.filter((r) => r.role === 'installation').length,
      equivalent: rels.filter((r) => r.role === 'equivalent').length,
      supersedes: rels.filter((r) => r.role === 'supersedes').length,
    };
  }, [rels]);

  // Zoom / Pan handlers
  const handleZoomIn = () => setZoomLevel((z) => Math.min(z + 0.15, 1.6));
  const handleZoomOut = () => setZoomLevel((z) => Math.max(z - 0.15, 0.65));
  const handleResetZoom = () => {
    setZoomLevel(1);
    setPanOffset({ x: 0, y: 0 });
  };

  // Color & badge helper for relationship roles
  const getRoleTheme = (role: string) => {
    switch (role) {
      case 'primary':
        return {
          stroke: '#0f766e',
          fill: '#134e4a',
          bg: 'bg-teal-900',
          text: 'text-white',
          badgeBg: 'bg-teal-50',
          badgeText: 'text-teal-800',
          border: 'border-teal-300',
          dot: 'bg-teal-600',
          label: 'Primary Applicable Standard',
        };

      case 'safety':
        return {
          stroke: '#d97706',
          fill: '#fffbeb',
          bg: 'bg-amber-50',
          text: 'text-amber-900',
          badgeBg: 'bg-amber-50',
          badgeText: 'text-amber-900',
          border: 'border-amber-300',
          dot: 'bg-amber-500',
          label: 'Safety Standard',
        };
      case 'normative':
        return {
          stroke: '#2563eb',
          fill: '#eff6ff',
          bg: 'bg-blue-50',
          text: 'text-blue-900',
          badgeBg: 'bg-blue-50',
          badgeText: 'text-blue-800',
          border: 'border-blue-300',
          dot: 'bg-blue-600',
          label: 'Normative Reference',
        };
      case 'testing':
        return {
          stroke: '#9333ea',
          fill: '#faf5ff',
          bg: 'bg-purple-50',
          text: 'text-purple-900',
          badgeBg: 'bg-purple-50',
          badgeText: 'text-purple-800',
          border: 'border-purple-300',
          dot: 'bg-purple-600',
          label: 'Testing Protocol',
        };
      case 'installation':
        return {
          stroke: '#059669',
          fill: '#ecfdf5',
          bg: 'bg-emerald-50',
          text: 'text-emerald-900',
          badgeBg: 'bg-emerald-50',
          badgeText: 'text-emerald-800',
          border: 'border-emerald-300',
          dot: 'bg-emerald-600',
          label: 'Design & Installation',
        };
      case 'equivalent':
        return {
          stroke: '#0284c7',
          fill: '#f0f9ff',
          bg: 'bg-sky-50',
          text: 'text-sky-900',
          badgeBg: 'bg-sky-50',
          badgeText: 'text-sky-800',
          border: 'border-sky-300',
          dot: 'bg-sky-600',
          label: 'International Equivalent',
        };
      case 'supersedes':
        return {
          stroke: '#dc2626',
          fill: '#fef2f2',
          bg: 'bg-error-50',
          text: 'text-error-900',
          badgeBg: 'bg-error-50',
          badgeText: 'text-error-800',
          border: 'border-error-300',
          dot: 'bg-error-500',
          label: 'Superseded / Withdrawn',
        };
      default:
        return {
          stroke: '#64748b',
          fill: '#f8fafc',
          bg: 'bg-ink-100',
          text: 'text-ink-800',
          badgeBg: 'bg-ink-100',
          badgeText: 'text-ink-700',
          border: 'border-ink-200',
          dot: 'bg-ink-500',
          label: 'Related Standard',
        };
    }
  };

  // ─── LED DEMO ONLY ───────────────────────────────────────────────────────────
  // Rich relationship card view for the an-001 LED demo fixture.
  // This early-return is reached only when analysisId === 'an-001' (a seeded
  // analysis, so isReal is always false here). Real backend uploads never match
  // 'an-001' and are unaffected. Other seeded demos (an-002/003, an-hindi, etc.)
  // also pass through to their normal paths below.
  if (!isReal && (analysis?.id === 'an-001' || sourceAnalysisId === 'an-001')) {
    const countByRole = (role: string) => rels.filter((r) => r.role === role).length;

    const roleSummary: Array<{ role: string; label: string; count: number }> = [
      { role: 'normative',    label: 'Normative Reference',         count: countByRole('normative') },
      { role: 'testing',      label: 'Testing Protocol',            count: countByRole('testing') },
      { role: 'safety',       label: 'Safety Standard',             count: countByRole('safety') },
      { role: 'installation', label: 'Design & Installation',       count: countByRole('installation') },
      { role: 'equivalent',   label: 'International Equivalent',    count: countByRole('equivalent') },
      { role: 'supersedes',   label: 'Superseded / Withdrawn',      count: countByRole('supersedes') },
    ].filter((s) => s.count > 0);

    return (
      <div className="space-y-6">
        {/* ── Summary count strip ─────────────────────────────────────── */}
        <div className="flex flex-wrap items-center gap-2 pb-3 border-b border-ink-100">
          <span className="text-xs font-bold text-ink-700 mr-1 font-mono uppercase tracking-wider">
            Relationship Summary:
          </span>
          {roleSummary.map(({ role, label, count }) => {
            const theme = getRoleTheme(role);
            return (
              <span
                key={role}
                className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold font-mono ${theme.badgeBg} ${theme.badgeText} border-current/30`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${theme.dot}`} />
                {count} {label}
              </span>
            );
          })}
        </div>

        {/* ── Relationship cards ──────────────────────────────────────── */}
        <div className="grid grid-cols-1 gap-5">
          {rels.map((rel) => {
            const theme = getRoleTheme(rel.role || 'normative');
            const fromStd = localGetStandardById(rel.fromStandardId);
            const toStd   = localGetStandardById(rel.toStandardId);
            const fromLabel = fromStd?.number ?? rel.fromStandardId;
            const toLabel   = toStd?.number   ?? rel.toStandardId;

            return (
              <div
                key={rel.id}
                className="rounded-xl border border-ink-200 bg-white shadow-soft hover:shadow-md transition-shadow overflow-hidden"
              >
                {/* Coloured top bar matching role */}
                <div className="h-1" style={{ backgroundColor: theme.stroke }} />

                <div className="p-5">
                  {/* Card header: type badge + clause + title */}
                  <div className="flex flex-wrap items-start gap-3 pb-4 mb-4 border-b border-ink-100">
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2 mb-1.5">
                        <span
                          className={`inline-block rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest font-mono ${theme.badgeBg} ${theme.badgeText}`}
                        >
                          {theme.label}
                        </span>
                        {rel.clause && (
                          <span className="text-[11px] font-mono text-ink-400">{rel.clause}</span>
                        )}
                      </div>

                      {/* Source → Target */}
                      <div className="flex items-center gap-2 mt-1">
                        <button
                          onClick={() => fromStd && navigate({ name: 'standard', standardId: fromStd.id })}
                          className={`font-mono font-bold text-sm ${fromStd ? 'text-ink-900 hover:text-teal-700 underline underline-offset-2' : 'text-ink-600 cursor-default'}`}
                        >
                          {fromLabel}
                        </button>
                        <ArrowRight size={14} className="text-ink-400 shrink-0" />
                        <button
                          onClick={() => toStd && navigate({ name: 'standard', standardId: toStd.id })}
                          className={`font-mono font-bold text-sm ${toStd ? 'text-ink-900 hover:text-teal-700 underline underline-offset-2' : 'text-ink-600 cursor-default'}`}
                        >
                          {toLabel}
                        </button>
                      </div>

                      <h4 className="mt-1 text-base font-semibold text-ink-800">
                        {rel.label ?? `${fromLabel} → ${toLabel}`}
                      </h4>
                    </div>
                  </div>

                  {/* Two-column body */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                    {/* Nature of relationship */}
                    <div>
                      <h5 className="text-[11px] font-bold uppercase tracking-wider text-ink-400 font-mono mb-2">
                        Why they're related
                      </h5>
                      <p className="text-sm text-ink-700 leading-relaxed">{rel.description}</p>
                    </div>

                    {/* Procurement impact */}
                    {rel.whyMatters && (
                      <div>
                        <h5 className="text-[11px] font-bold uppercase tracking-wider text-teal-600 font-mono mb-2">
                          Procurement impact
                        </h5>
                        <p className="text-sm text-teal-900 leading-relaxed bg-teal-50/60 border border-teal-100 rounded-lg p-3">
                          {rel.whyMatters}
                        </p>
                      </div>
                    )}
                  </div>

                  {/* Evidence footer */}
                  {(rel.evidenceSnippet || rel.evidenceSource) && (
                    <div className="mt-5 rounded-lg bg-ink-50 border border-ink-100 p-3">
                      {rel.evidenceSource && (
                        <div className="flex items-center gap-2 mb-1">
                          <FileText size={11} className="text-ink-400 shrink-0" />
                          <span className="text-[10px] font-bold uppercase tracking-wider text-ink-400 font-mono">
                            Evidence:
                          </span>
                          <span className="text-[11px] font-semibold text-ink-600">{rel.evidenceSource}</span>
                        </div>
                      )}
                      {rel.evidenceSnippet && (
                        <p className="text-xs text-ink-500 font-mono italic leading-relaxed">
                          {rel.evidenceSnippet}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // Real analyses: the hardcoded LED force-graph (with non-null getStandardById
  // assertions) can't render — show a clean references list from the adapter data.
  if (isReal) {
    return (
      <div className="space-y-4">
        <Card padding="lg" className="bg-white border-ink-200 shadow-soft">
          <div className="flex items-center gap-2 border-b border-ink-100 pb-3 mb-4">
            <GitBranch size={16} className="text-teal-700" />
            <div>
              <h3 className="text-sm font-semibold text-ink-900">Standard References &amp; Relationships</h3>
              <p className="text-xs text-ink-500 mt-0.5">
                Normative references cited by the matched standards for this procurement.
              </p>
            </div>
          </div>
          {rels.length === 0 ? (
            <div className="py-10 text-center">
              <Share2 size={22} className="mx-auto mb-2 text-ink-300" />
              <p className="text-sm font-medium text-ink-700">No normative/cross-reference relationships identified.</p>
              <p className="mx-auto mt-1 max-w-sm text-xs text-ink-400">
                Relationships appear when a matched standard cites other Indian or international
                standards as normative references.
              </p>
            </div>
          ) : (
            <ul className="space-y-2.5">
              {rels.map((rel) => {
                const from = localGetStandardById(rel.fromStandardId);
                return (
                  <li
                    key={rel.id}
                    className="rounded-lg border border-ink-100 bg-ivory-50/40 p-3 text-xs transition-colors hover:border-ink-200"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-mono font-semibold text-ink-900">{rel.label}</span>
                      {from && (
                        <button
                          onClick={() => navigate({ name: 'standard', standardId: from.id })}
                          className="inline-flex items-center gap-1 font-medium text-teal-700 hover:text-teal-900"
                        >
                          View {from.number} <ArrowRight size={12} />
                        </button>
                      )}
                    </div>
                    {rel.description && (
                      <p className="mt-1 leading-relaxed text-ink-600">{rel.description}</p>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* ------------------------------------------------------------------ */}
      {/* 1. RELATIONSHIP SUMMARY METRIC STRIP & INTRO                       */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 border-b border-ink-100 pb-3.5">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-bold text-ink-900 tracking-tight">
              Standards Ecosystem & Relationship Graph
            </h2>
            <span className="rounded bg-teal-50 px-2 py-0.5 text-[10px] font-semibold text-teal-800 border border-teal-200 font-mono">
              8 Standards Mapped
            </span>
          </div>
          <p className="text-xs text-ink-500 mt-0.5">
            Standards operate as an interconnected ecosystem. Understand primary, normative, testing, and safety dependencies.
          </p>
        </div>

        {/* Compact Summary Metrics Strip */}
        <div className="flex flex-wrap items-center gap-1.5 font-mono text-[11px]">
          <span className="rounded bg-teal-900 text-white px-2 py-0.5 font-semibold">
            Primary: {relCounts.primary}
          </span>
          <span className="rounded bg-blue-50 text-blue-800 border border-blue-200 px-2 py-0.5">
            Normative: {relCounts.normative}
          </span>
          <span className="rounded bg-purple-50 text-purple-800 border border-purple-200 px-2 py-0.5">
            Testing: {relCounts.testing}
          </span>
          <span className="rounded bg-amber-50 text-amber-900 border border-amber-200 px-2 py-0.5">
            Safety: {relCounts.safety}
          </span>
          <span className="rounded bg-emerald-50 text-emerald-800 border border-emerald-200 px-2 py-0.5">
            Installation: {relCounts.installation}
          </span>
          <span className="rounded bg-sky-50 text-sky-800 border border-sky-200 px-2 py-0.5">
            International: {relCounts.equivalent}
          </span>
          <span className="rounded bg-error-50 text-error-800 border border-error-200 px-2 py-0.5">
            Superseded: {relCounts.supersedes}
          </span>
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* 2. FILTER & TOOLBAR STRIP                                          */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-white p-2.5 rounded-xl border border-ink-200 shadow-soft">
        {/* Relationship Filter Tabs */}
        <div className="flex items-center gap-1 overflow-x-auto pb-1 sm:pb-0">
          <span className="text-[11px] font-semibold uppercase text-ink-400 font-mono mr-1">
            Filter:
          </span>
          {[
            { id: 'all', label: 'All Connections' },
            { id: 'normative', label: 'Normative' },
            { id: 'testing', label: 'Testing' },
            { id: 'safety', label: 'Safety' },
            { id: 'installation', label: 'Installation' },
            { id: 'equivalent', label: 'Equivalent' },
            { id: 'supersedes', label: 'Superseded' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveFilter(tab.id as FilterType)}
              className={`rounded px-2.5 py-1 text-xs font-mono font-medium transition-colors whitespace-nowrap ${
                activeFilter === tab.id
                  ? 'bg-ink-900 text-white'
                  : 'bg-ivory-100 text-ink-600 hover:bg-ivory-200'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Graph Canvas Controls (Zoom, Fit, Reset) */}
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            onClick={handleZoomIn}
            className="rounded border border-ink-200 bg-white p-1 text-ink-600 hover:bg-ivory-100 hover:text-ink-900 transition-colors"
            title="Zoom In"
          >
            <Plus size={14} />
          </button>
          <button
            onClick={handleZoomOut}
            className="rounded border border-ink-200 bg-white p-1 text-ink-600 hover:bg-ivory-100 hover:text-ink-900 transition-colors"
            title="Zoom Out"
          >
            <Minus size={14} />
          </button>
          <button
            onClick={handleResetZoom}
            className="rounded border border-ink-200 bg-white px-2 py-1 text-[11px] font-mono font-medium text-ink-600 hover:bg-ivory-100 hover:text-ink-900 transition-colors flex items-center gap-1"
            title="Fit to Canvas"
          >
            <RotateCcw size={12} /> Fit Graph
          </button>
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* 3. MAIN GRAPH & SIDE INSPECTOR SPLIT VIEW                         */}
      {/* ------------------------------------------------------------------ */}
      <div className="grid gap-4 lg:grid-cols-12">
        {/* GRAPH CANVAS (7 or 8 Columns) */}
        <div className="lg:col-span-8 rounded-xl border border-ink-200 bg-white p-3 shadow-soft relative overflow-hidden flex flex-col justify-between min-h-[540px]">
          {/* Canvas Background subtle dot grid */}
          <div
            ref={containerRef}
            className="relative flex-1 w-full h-full min-h-[460px] overflow-hidden select-none bg-[radial-gradient(#cbd5e1_1px,transparent_1px)] [background-size:16px_16px]"
          >
            <svg
              viewBox="0 0 840 520"
              className="w-full h-full cursor-grab active:cursor-grabbing transition-transform duration-200"
              style={{
                transform: `scale(${zoomLevel}) translate(${panOffset.x}px, ${panOffset.y}px)`,
                transformOrigin: 'center center',
              }}
            >
              {/* Arrow Marker Definitions */}
              <defs>
                <marker
                  id="arrow-teal"
                  viewBox="0 0 10 10"
                  refX="22"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#0f766e" />
                </marker>
                <marker
                  id="arrow-blue"
                  viewBox="0 0 10 10"
                  refX="22"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#2563eb" />
                </marker>
                <marker
                  id="arrow-purple"
                  viewBox="0 0 10 10"
                  refX="22"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#9333ea" />
                </marker>
                <marker
                  id="arrow-amber"
                  viewBox="0 0 10 10"
                  refX="22"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#d97706" />
                </marker>
                <marker
                  id="arrow-emerald"
                  viewBox="0 0 10 10"
                  refX="22"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#059669" />
                </marker>
                <marker
                  id="arrow-error"
                  viewBox="0 0 10 10"
                  refX="22"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#dc2626" />
                </marker>
              </defs>

              {/* ---------------------------------------------------------- */}
              {/* EDGES & CONNECTIONS                                        */}
              {/* ---------------------------------------------------------- */}
              {visibleRels.map((rel) => {
                const fromNode = graphNodes.find((n) => n.id === rel.fromStandardId);
                const toNode = graphNodes.find((n) => n.id === rel.toStandardId);
                if (!fromNode || !toNode) return null;

                const isConnectedToSelected =
                  fromNode.id === selectedNodeId || toNode.id === selectedNodeId;
                const theme = getRoleTheme(rel.role || 'normative');

                const midX = (fromNode.x + toNode.x) / 2;
                const midY = (fromNode.y + toNode.y) / 2;

                let markerId = 'arrow-teal';
                if (rel.role === 'normative') markerId = 'arrow-blue';
                if (rel.role === 'testing') markerId = 'arrow-purple';
                if (rel.role === 'safety') markerId = 'arrow-amber';
                if (rel.role === 'installation') markerId = 'arrow-emerald';
                if (rel.role === 'supersedes') markerId = 'arrow-error';

                return (
                  <g key={rel.id} className="transition-opacity duration-200">
                    {/* Background line */}
                    <line
                      x1={fromNode.x}
                      y1={fromNode.y}
                      x2={toNode.x}
                      y2={toNode.y}
                      stroke={isConnectedToSelected ? theme.stroke : '#cbd5e1'}
                      strokeWidth={isConnectedToSelected ? 2.5 : 1.5}
                      strokeDasharray={rel.role === 'supersedes' ? '4 3' : undefined}
                      markerEnd={`url(#${markerId})`}
                      className="transition-all"
                    />

                    {/* Edge Label Badge with text */}
                    <g transform={`translate(${midX}, ${midY})`}>
                      <rect
                        x="-70"
                        y="-10"
                        width="140"
                        height="20"
                        rx="4"
                        fill="#ffffff"
                        stroke={isConnectedToSelected ? theme.stroke : '#e2e8f0'}
                        strokeWidth="1"
                        className="shadow-xs"
                      />
                      <text
                        x="0"
                        y="3.5"
                        textAnchor="middle"
                        className="text-[9.5px] font-mono font-medium fill-ink-700 pointer-events-none select-none"
                      >
                        {rel.label || rel.type}
                      </text>
                    </g>
                  </g>
                );
              })}

              {/* ---------------------------------------------------------- */}
              {/* GRAPH NODES                                                */}
              {/* ---------------------------------------------------------- */}
              {visibleNodes.map((node) => {
                const isSelected = node.id === selectedNodeId;
                const isPrimary = node.isPrimary;
                const theme = getRoleTheme(node.role);
                const hasIssue = node.standard.status !== 'current';

                // Degree of focus: is it selected or connected to selected?
                const isDirectlyConnected =
                  isSelected ||
                  rels.some(
                    (r) =>
                      (r.fromStandardId === node.id && r.toStandardId === selectedNodeId) ||
                      (r.toStandardId === node.id && r.fromStandardId === selectedNodeId)
                  );

                return (
                  <g
                    key={node.id}
                    transform={`translate(${node.x}, ${node.y})`}
                    onClick={() => setSelectedNodeId(node.id)}
                    className="cursor-pointer transition-all duration-200"
                    opacity={isDirectlyConnected ? 1 : 0.45}
                  >
                    {/* Primary Node Card (Center) */}
                    {isPrimary ? (
                      <g>
                        {/* Outer Selection Highlight Ring */}
                        <rect
                          x="-105"
                          y="-45"
                          width="210"
                          height="90"
                          rx="10"
                          fill="#0f172a"
                          stroke={isSelected ? '#14b8a6' : '#334155'}
                          strokeWidth={isSelected ? '3' : '1.5'}
                          className="shadow-lg"
                        />
                        <text
                          x="0"
                          y="-20"
                          textAnchor="middle"
                          className="text-[10px] font-mono uppercase tracking-wider font-bold fill-teal-400"
                        >
                          PRIMARY STANDARD
                        </text>
                        <text
                          x="0"
                          y="2"
                          textAnchor="middle"
                          className="text-xs font-mono font-bold fill-white"
                        >
                          {node.standard.number}
                        </text>
                        <text
                          x="0"
                          y="20"
                          textAnchor="middle"
                          className="text-[10px] font-sans fill-slate-300"
                        >
                          Road & Street Lighting Luminaires
                        </text>
                        <text
                          x="0"
                          y="34"
                          textAnchor="middle"
                          className="text-[9px] font-mono fill-teal-300"
                        >
                          CURRENT · 91% APPLICABILITY
                        </text>
                      </g>
                    ) : (
                      /* Peripheral Nodes */
                      <g>
                        <rect
                          x="-85"
                          y="-35"
                          width="170"
                          height="70"
                          rx="8"
                          fill="#ffffff"
                          stroke={isSelected ? theme.stroke : hasIssue ? '#fca5a5' : '#cbd5e1'}
                          strokeWidth={isSelected ? '2.5' : '1.2'}
                          className="shadow-sm hover:shadow-md transition-shadow"
                        />
                        {/* Status bar top */}
                        <rect
                          x="-85"
                          y="-35"
                          width="170"
                          height="5"
                          rx="2"
                          fill={theme.stroke}
                        />
                        <text
                          x="0"
                          y="-16"
                          textAnchor="middle"
                          className="text-[9px] font-mono font-semibold uppercase fill-ink-500"
                        >
                          {theme.label}
                        </text>
                        <text
                          x="0"
                          y="3"
                          textAnchor="middle"
                          className="text-[11px] font-mono font-bold fill-ink-900"
                        >
                          {node.standard.number}
                        </text>
                        <text
                          x="0"
                          y="19"
                          textAnchor="middle"
                          className="text-[9.5px] font-sans fill-ink-600"
                        >
                          {node.standard.title.substring(0, 24)}…
                        </text>
                      </g>
                    )}
                  </g>
                );
              })}
            </svg>
          </div>

          {/* Visual Legend bar below graph */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 pt-2 text-[11px] text-ink-600 font-mono">
            <span className="font-semibold text-ink-900 font-sans">Legend:</span>
            <div className="flex flex-wrap items-center gap-3">
              <span className="flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full bg-teal-900" /> Primary Code
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full bg-blue-600" /> Normative
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full bg-purple-600" /> Testing
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full bg-amber-500" /> Safety
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-600" /> Installation
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full bg-sky-600" /> International
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-full bg-error-500" /> Superseded
              </span>
            </div>
          </div>
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* 4. RIGHT-SIDE NODE INSPECTOR DRAWER / PANEL                        */}
        {/* ------------------------------------------------------------------ */}
        <div className="lg:col-span-4 space-y-3">
          <Card padding="md" className="bg-white border-ink-200 shadow-soft h-full flex flex-col justify-between">
            <div className="space-y-3.5">
              {/* Inspector Header */}
              <div className="border-b border-ink-100 pb-3">
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-teal-800 font-mono bg-teal-50 px-2 py-0.5 rounded border border-teal-200">
                    {selectedNode.isPrimary ? 'Primary Standard' : getRoleTheme(selectedNode.role).label}
                  </span>
                  <Badge variant={statusConfig[selectedStandard.status].variant}>
                    {statusConfig[selectedStandard.status].label}
                  </Badge>
                </div>

                <h3 className="font-mono text-base font-bold text-ink-900">
                  {selectedStandard.number}
                </h3>
                <p className="text-xs text-ink-700 font-medium mt-0.5 leading-snug">
                  {selectedStandard.title}
                </p>

                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-400 font-mono">
                  <span>Edition {selectedStandard.edition} ({selectedStandard.revision})</span>
                  <span>·</span>
                  <span>Section {selectedStandard.section}</span>
                  {selectedStandard.applicabilityScore && (
                    <>
                      <span>·</span>
                      <span className="text-teal-700 font-semibold">
                        {selectedStandard.applicabilityScore}% match
                      </span>
                    </>
                  )}
                </div>
              </div>

              {/* Why Connected to Primary Standard */}
              <div>
                <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-400 font-mono block mb-1">
                  Why it is connected in this procurement
                </span>
                <p className="text-xs text-ink-700 leading-relaxed bg-ivory-50/70 p-2.5 rounded-lg border border-ink-100">
                  {selectedRelationship?.description ||
                    selectedStandard.whyApplies ||
                    'Primary governing specification establishing fundamental mechanical, optical, and environmental rules.'}
                </p>
              </div>

              {/* Why This Relationship Matters */}
              <div>
                <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-400 font-mono block mb-1">
                  Why this relationship matters
                </span>
                <div className="rounded-lg border border-teal-200/80 bg-teal-50/30 p-2.5 text-xs text-ink-800 leading-relaxed">
                  {selectedRelationship?.whyMatters ||
                    'Defines the overarching technical framework for tender compliance, evaluation criteria, and laboratory testing.'}
                </div>
              </div>

              {/* Evidence Connection Chain */}
              <div>
                <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-400 font-mono block mb-1.5">
                  Evidence Connection Chain
                </span>

                <div className="rounded-lg border border-ink-100 bg-white p-2.5 text-xs space-y-1.5 font-mono">
                  <div className="flex items-center gap-1.5 text-teal-900 font-semibold">
                    <span className="h-1.5 w-1.5 rounded-full bg-teal-600" />
                    <span>Primary Standard: {primaryStd.number}</span>
                  </div>
                  <div className="pl-3 text-[11px] text-ink-400 flex items-center gap-1">
                    <ArrowDown size={11} />
                    <span>{selectedRelationship?.label || 'Direct Governing Mandate'}</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-ink-800 font-semibold">
                    <span className="h-1.5 w-1.5 rounded-full bg-blue-600" />
                    <span>Referenced Standard: {selectedStandard.number}</span>
                  </div>

                  {selectedRelationship?.evidenceSnippet && (
                    <blockquote className="mt-2 border-l-2 border-teal-500 pl-2.5 text-[11px] italic text-ink-700 bg-ivory-50 p-1.5 rounded-r font-sans leading-relaxed">
                      {selectedRelationship.evidenceSnippet}
                      <span className="block mt-1 font-mono text-[10px] text-teal-800 font-semibold not-italic">
                        Source: {selectedRelationship.evidenceSource}
                      </span>
                    </blockquote>
                  )}
                </div>
              </div>
            </div>

            {/* Inspector Actions */}
            <div className="pt-3 border-t border-ink-100 flex flex-col gap-2">
              <Button
                variant="primary"
                size="sm"
                className="w-full"
                onClick={() => navigate({ name: 'standard', standardId: selectedStandard.id })}
                rightIcon={<ExternalLink size={13} />}
              >
                View Full Standard Details
              </Button>

              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  className="flex-1"
                  onClick={() => {
                    setIsCompareModalOpen(true);
                  }}
                  leftIcon={<Columns size={13} />}
                >
                  Compare with Primary
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => navigate({ name: 'analysis', analysisId, tab: 'standards' })}
                >
                  Standards Tab
                </Button>
              </div>
            </div>
          </Card>
        </div>
      </div>

      {/* Comparison Modal between selected and primary */}
      <StandardComparisonModal
        standardAId={primaryStd.id}
        standardBId={selectedStandard.id === primaryStd.id ? 'std-15885' : selectedStandard.id}
        isOpen={isCompareModalOpen}
        onClose={() => setIsCompareModalOpen(false)}
      />
    </div>
  );
}

