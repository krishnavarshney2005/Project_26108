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

  // ─── RELATIONSHIPS VIEW (FOR ALL ANALYSES) ─────────────────────────────────
  // Rich relationship card view dynamically driven by relationship data.
  const countByRole = (role: string) => rels.filter((r) => r.role === role).length;

  const roleSummary: Array<{ role: string; label: string; count: number }> = [
    { role: 'normative',    label: 'Normative Reference',         count: countByRole('normative') },
    { role: 'testing',      label: 'Testing Protocol',            count: countByRole('testing') },
    { role: 'safety',       label: 'Safety Standard',             count: countByRole('safety') },
    { role: 'installation', label: 'Design & Installation',       count: countByRole('installation') },
    { role: 'equivalent',   label: 'International Equivalent',    count: countByRole('equivalent') },
    { role: 'supersedes',   label: 'Superseded / Withdrawn',      count: countByRole('supersedes') },
  ].filter((s) => s.count > 0);

  if (rels.length === 0) {
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
          <div className="py-10 text-center">
            <Share2 size={22} className="mx-auto mb-2 text-ink-300" />
            <p className="text-sm font-medium text-ink-700">No normative/cross-reference relationships identified.</p>
            <p className="mx-auto mt-1 max-w-sm text-xs text-ink-400">
              Relationships appear when a matched standard cites other Indian or international
              standards as normative references.
            </p>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ── Summary count strip ─────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2 pb-3 border-b border-ink-100">
        <span className="text-xs font-bold text-ink-700 mr-1 font-mono uppercase tracking-wider">
          Relationship Summary:
        </span>
        {roleSummary.length > 0 ? roleSummary.map(({ role, label, count }) => {
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
        }) : (
           <span className="text-xs font-mono text-ink-500">{rels.length} Connected Standards</span>
        )}
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
                  </div>
                </div>

                {/* Content Sections */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                  {/* Left Col: Explanation */}
                  <div className="space-y-4">
                    <div>
                      <h5 className="text-[11px] font-bold uppercase tracking-wider text-ink-500 font-mono mb-2 flex items-center gap-1.5">
                        <Link size={12} />
                        Nature of Relationship
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

                  {/* Right Col: Evidence Snippet (if any) */}
                  {rel.evidenceSnippet && (
                    <div className="md:border-l md:border-ink-100 md:pl-5 space-y-3">
                      <h5 className="text-[11px] font-bold uppercase tracking-wider text-amber-700 font-mono flex items-center gap-1.5">
                        <FileText size={12} />
                        Evidence in Standard
                      </h5>
                      <div className="rounded border border-amber-200/60 bg-amber-50/50 p-3 relative">
                        <Quote size={14} className="absolute text-amber-200 -top-1 -left-1" />
                        <p className="text-xs text-amber-900 italic leading-relaxed relative z-10 pl-2">
                          {rel.evidenceSnippet}
                        </p>
                      </div>
                      {rel.evidenceSource && (
                        <div className="text-[10px] font-mono text-ink-400 mt-2">
                          Source: {rel.evidenceSource}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );

}
