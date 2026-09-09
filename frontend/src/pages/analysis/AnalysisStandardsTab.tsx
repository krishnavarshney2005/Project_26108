import { useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  BookMarked,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock,
  Columns,
  ExternalLink,
  FileCheck2,
  FileText,
  FileWarning,
  HelpCircle,
  Layers,
  Scale,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { useRouter } from '@/router';
import {
  statusConfig,
  getStandardById,
  getMatchedRequirementsByAnalysisId,
} from '@/data/mockData';
import type {
  Analysis,
  HumanDecision,
  HumanReviewConfidence,
  Standard,
  StandardRelationshipRole,
} from '@/data/types';
import { StandardComparisonModal } from '@/components/standards/StandardComparisonModal';

interface Props {
  analysis: Analysis;
}

export function AnalysisStandardsTab({ analysis }: Props) {
  const { navigate } = useRouter();
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<'all' | 'primary' | 'normative' | 'testing' | 'issues'>('all');
  const [compareModalOpen, setCompareModalOpen] = useState(false);
  const [compareA, setCompareA] = useState('std-10322');
  const [compareB, setCompareB] = useState('std-1944');

  const allMatchedRequirements = getMatchedRequirementsByAnalysisId(analysis.id);

  const matchedStandards = analysis.matchedStandardIds
    .map((id) => getStandardById(id))
    .filter((s): s is Standard => s !== undefined);


  // Local state for officer human decisions on standards
  const [decisions, setDecisions] = useState<Record<string, HumanDecision>>({
    'std-10322': 'accepted',
    'std-15885': 'accepted',
    'std-16107': 'accepted',
    'std-60529': 'accepted',
    'std-14700': 'reviewed',
    'std-1944': 'reviewed',
    'std-sp-72': 'accepted',
  });

  const handleDecision = (stdId: string, decision: HumanDecision) => {
    setDecisions((prev) => ({ ...prev, [stdId]: decision }));
  };

  const filtered = matchedStandards.filter((s) => {
    if (
      search &&
      !s.title.toLowerCase().includes(search.toLowerCase()) &&
      !s.number.toLowerCase().includes(search.toLowerCase()) &&
      !s.summary.toLowerCase().includes(search.toLowerCase())
    ) {
      return false;
    }
    if (filter === 'primary') return s.relationshipRole === 'primary';
    if (filter === 'normative') return s.relationshipRole === 'normative' || s.relationshipRole === 'safety';
    if (filter === 'testing') return s.relationshipRole === 'testing' || s.relationshipRole === 'installation';
    if (filter === 'issues') return s.status !== 'current' || s.reviewConfidence === 'needs-review';
    return true;
  });

  // Relationship label & badge renderer
  const renderRelationshipBadge = (role?: StandardRelationshipRole) => {
    switch (role) {
      case 'primary':
        return (
          <span className="inline-flex items-center gap-1 rounded bg-teal-800 text-white px-2 py-0.5 text-[11px] font-semibold tracking-wide uppercase font-mono shadow-soft">
            Primary Code
          </span>
        );
      case 'normative':
        return (
          <span className="inline-flex items-center gap-1 rounded bg-blue-50 text-blue-800 border border-blue-200 px-2 py-0.5 text-[11px] font-medium font-mono">
            Normative Reference
          </span>
        );
      case 'testing':
        return (
          <span className="inline-flex items-center gap-1 rounded bg-purple-50 text-purple-800 border border-purple-200 px-2 py-0.5 text-[11px] font-medium font-mono">
            Testing Protocol
          </span>
        );
      case 'safety':
        return (
          <span className="inline-flex items-center gap-1 rounded bg-amber-50 text-amber-900 border border-amber-200 px-2 py-0.5 text-[11px] font-medium font-mono">
            Safety Standard
          </span>
        );
      case 'installation':
        return (
          <span className="inline-flex items-center gap-1 rounded bg-emerald-50 text-emerald-800 border border-emerald-200 px-2 py-0.5 text-[11px] font-medium font-mono">
            Design & Installation
          </span>
        );
      case 'related':
      default:
        return (
          <span className="inline-flex items-center gap-1 rounded bg-ink-100 text-ink-700 border border-ink-200 px-2 py-0.5 text-[11px] font-medium font-mono">
            Related Reference
          </span>
        );
    }
  };

  // Human confidence status badge renderer
  const renderConfidenceBadge = (confidence?: HumanReviewConfidence) => {
    switch (confidence) {
      case 'high-confidence':
        return (
          <span className="inline-flex items-center gap-1 rounded bg-teal-50 px-2 py-0.5 text-[11px] font-semibold text-teal-800 border border-teal-200">
            <CheckCircle2 size={11} className="text-teal-600" />
            High confidence
          </span>
        );
      case 'needs-review':
        return (
          <span className="inline-flex items-center gap-1 rounded bg-warning-50 px-2 py-0.5 text-[11px] font-semibold text-warning-800 border border-warning-200">
            <AlertTriangle size={11} className="text-warning-600" />
            Needs review
          </span>
        );
      case 'insufficient-evidence':
        return (
          <span className="inline-flex items-center gap-1 rounded bg-error-50 px-2 py-0.5 text-[11px] font-semibold text-error-800 border border-error-200">
            <ShieldAlert size={11} className="text-error-600" />
            Insufficient evidence
          </span>
        );
      default:
        return null;
    }
  };

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-ink-100 pb-3">
        <div className="flex items-center gap-2 overflow-x-auto pb-1 sm:pb-0">
          <div className="flex rounded-lg border border-ink-200 bg-white p-0.5">
            {[
              { id: 'all', label: `All Standards (${matchedStandards.length})` },
              { id: 'primary', label: 'Primary' },
              { id: 'normative', label: 'Normative / Safety' },
              { id: 'testing', label: 'Testing / Design' },
              { id: 'issues', label: 'Needs Attention' },
            ].map((f) => (
              <button
                key={f.id}
                onClick={() => setFilter(f.id as any)}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors whitespace-nowrap ${
                  filter === f.id ? 'bg-ink-900 text-white' : 'text-ink-500 hover:text-ink-700'
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search IS number, title, keywords…"
            className="w-full rounded-lg border border-ink-200 bg-white py-1.5 pl-7 pr-3 text-sm text-ink-700 placeholder:text-ink-400 focus:border-teal-500 focus:outline-none sm:w-64"
          />
        </div>
      </div>

      {/* Standards list */}
      <div className="space-y-3.5">
        {filtered.map((standard) => {
          const status = statusConfig[standard.status];
          const hasIssue = standard.status !== 'current';
          const decision = decisions[standard.id] || 'accepted';

          const standardReqs = allMatchedRequirements.filter(
            (req) => req.standardId === standard.id || req.standardCode.includes(standard.number.split(' ')[1] || '')
          );

          return (
            <Card
              key={standard.id}
              padding="lg"
              className={`bg-white transition-all ${
                standard.relationshipRole === 'primary'
                  ? 'border-teal-300 ring-1 ring-teal-500/10 shadow-soft'
                  : 'border-ink-200 shadow-soft'
              }`}
            >
              <div className="flex flex-col gap-4">
                {/* Header row of standard item */}
                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                  <div className="flex items-start gap-3.5">
                    <div
                      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg font-mono text-xs font-bold ${
                        standard.relationshipRole === 'primary'
                          ? 'bg-ink-900 text-teal-400'
                          : hasIssue
                          ? 'bg-warning-100 text-warning-800'
                          : 'bg-ivory-100 text-ink-700'
                      }`}
                    >
                      {hasIssue ? <FileWarning size={18} /> : <BookMarked size={18} />}
                    </div>

                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          onClick={() => navigate({ name: 'standard', standardId: standard.id })}
                          className="text-base font-semibold text-ink-900 hover:text-teal-700 flex items-center gap-1.5 font-mono"
                        >
                          {standard.number}
                          <ExternalLink size={13} className="text-ink-400" />
                        </button>
                        {renderRelationshipBadge(standard.relationshipRole)}
                        <Badge variant={status.variant}>{status.label}</Badge>
                        {renderConfidenceBadge(standard.reviewConfidence)}
                        {standard.regulatory && (
                          <Badge variant="blue" icon={<ShieldCheck size={11} />}>
                            Regulatory Order
                          </Badge>
                        )}
                        {standard.isCertified && (
                          <Badge variant="teal" icon={<CheckCircle2 size={11} />}>
                            Scheme-I ISI
                          </Badge>
                        )}
                      </div>


                      <h3 className="mt-1 text-sm font-medium text-ink-800">{standard.title}</h3>
                    </div>
                  </div>

                  {/* Applicability score & decision buttons */}
                  <div className="flex sm:flex-col items-center sm:items-end justify-between gap-1.5 shrink-0 border-t sm:border-t-0 pt-2 sm:pt-0 border-ink-100">
                    <div className="text-right">
                      <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-400 block font-sans">
                        Applicability score
                      </span>
                      <span className="font-mono text-sm font-bold text-ink-900 tabular-nums">
                        {standard.applicabilityScore != null ? `${standard.applicabilityScore}%` : '—'}
                      </span>
                    </div>

                    {/* Human Decision Buttons */}
                    <div className="flex items-center gap-1 text-xs">
                      <button
                        onClick={() => handleDecision(standard.id, 'accepted')}
                        className={`px-2 py-0.5 rounded text-[11px] font-medium transition-all ${
                          decision === 'accepted'
                            ? 'bg-success-600 text-white shadow-soft'
                            : 'bg-ivory-100 text-ink-600 hover:bg-ivory-200'
                        }`}
                      >
                        <Check size={11} className="inline mr-0.5" />
                        Accept
                      </button>
                      <button
                        onClick={() => handleDecision(standard.id, 'reviewed')}
                        className={`px-2 py-0.5 rounded text-[11px] font-medium transition-all ${
                          decision === 'reviewed'
                            ? 'bg-warning-500 text-white shadow-soft'
                            : 'bg-ivory-100 text-ink-600 hover:bg-ivory-200'
                        }`}
                      >
                        <HelpCircle size={11} className="inline mr-0.5" />
                        Review
                      </button>
                      <button
                        onClick={() => handleDecision(standard.id, 'rejected')}
                        className={`px-2 py-0.5 rounded text-[11px] font-medium transition-all ${
                          decision === 'rejected'
                            ? 'bg-error-600 text-white shadow-soft'
                            : 'bg-ivory-100 text-ink-600 hover:bg-ivory-200'
                        }`}
                      >
                        <X size={11} className="inline mr-0.5" />
                        Reject
                      </button>
                    </div>
                  </div>
                </div>

                {/* Structured Why it Applies Reasoning & Matched Requirements Badge */}
                <div className="rounded-lg border border-ink-100 bg-ivory-50/60 p-3 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
                    <span className="font-semibold text-ink-900 flex items-center gap-1.5 text-[11px] uppercase tracking-wider font-mono">
                      <Scale size={13} className="text-teal-700" />
                      Why it applies to this procurement:
                    </span>
                    <div className="flex items-center gap-1.5 font-mono text-[11px]">
                      {standardReqs.length > 0 && (
                        <span className="text-teal-800 bg-teal-50 px-2 py-0.5 rounded border border-teal-200 flex items-center gap-1 font-semibold">
                          <FileCheck2 size={11} />
                          {standardReqs.length} matched requirement{standardReqs.length > 1 ? 's' : ''}
                        </span>
                      )}
                      {standard.evidenceAvailable && (
                        <span className="text-teal-800 bg-teal-50 px-2 py-0.5 rounded border border-teal-200">
                          Evidence Available
                        </span>
                      )}
                    </div>
                  </div>

                  <p className="text-ink-700 leading-relaxed text-xs">
                    {standard.whyApplies || standard.summary}
                  </p>

                  {standard.whyAppliesReasons && standard.whyAppliesReasons.length > 0 && (
                    <div className="mt-2.5 grid gap-1.5 sm:grid-cols-2 pt-2 border-t border-ink-200/50">
                      {standard.whyAppliesReasons.map((r, idx) => (
                        <div key={idx} className="flex items-start gap-1.5 text-[11px]">
                          {r.matched ? (
                            <CheckCircle2 size={12} className="mt-0.5 shrink-0 text-teal-600" />
                          ) : (
                            <AlertTriangle size={12} className="mt-0.5 shrink-0 text-warning-600" />
                          )}
                          <span>
                            <strong className="text-ink-800 font-medium">{r.category}:</strong>{' '}
                            <span className="text-ink-600">{r.description}</span>
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Metadata & Actions footer */}
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 pt-2.5 text-xs text-ink-500 font-mono">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span>Edition: {standard.edition} ({standard.revision})</span>
                    <span>·</span>
                    <span>Bureau: {standard.bureau} ({standard.section})</span>
                    <span>·</span>
                    <span>{standard.pages} pages</span>
                    {standard.amendments && standard.amendments.length > 0 && (
                      <>
                        <span>·</span>
                        <span className="text-ink-700">{standard.amendments.join(', ')}</span>
                      </>
                    )}
                    {standard.retrievedAt && (
                      <>
                        <span>·</span>
                        <span>Verified: {standard.retrievedAt.slice(0, 10)}</span>
                      </>
                    )}
                    {standard.bisSourceUrl && (
                      <>
                        <span>·</span>
                        <a href={standard.bisSourceUrl} target="_blank" rel="noopener noreferrer" className="text-teal-600 hover:underline">BIS source ↗</a>
                      </>
                    )}
                  </div>

                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => {
                        setCompareA(standard.id);
                        setCompareB(standard.supersededBy || 'std-1944');
                        setCompareModalOpen(true);
                      }}
                      className="font-sans font-medium text-ink-600 hover:text-ink-900 inline-flex items-center gap-1 text-xs"
                    >
                      <Columns size={12} /> Compare
                    </button>
                    <button
                      onClick={() => navigate({ name: 'standard', standardId: standard.id })}
                      className="font-sans font-medium text-teal-700 hover:text-teal-900 inline-flex items-center gap-1 text-xs"
                    >
                      View details & clauses <ArrowRight size={13} />
                    </button>
                  </div>
                </div>
              </div>
            </Card>
          );
        })}
      </div>

      {/* Summary footer note */}
      <Card padding="md" className="mt-6 bg-ivory-100 border-ink-200">
        <div className="flex items-start gap-3">
          <AlertCircle size={16} className="mt-0.5 shrink-0 text-ink-600" />
          <div className="text-xs text-ink-700 leading-relaxed">
            <p className="font-semibold text-ink-900">Procurement Officer Advisory</p>
            <p className="mt-0.5">
              StandIQ provides source-backed evidence and clause mapping to support your specification decisions.
              All recommendations require official review before final incorporation into Tender corrigenda or evaluation matrices.
            </p>
          </div>
        </div>
      </Card>

      {/* Standard Comparison Modal */}
      <StandardComparisonModal
        standardAId={compareA}
        standardBId={compareB}
        isOpen={compareModalOpen}
        onClose={() => setCompareModalOpen(false)}
      />
    </div>
  );
}


