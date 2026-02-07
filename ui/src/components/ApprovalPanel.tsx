import type { PendingApproval } from '../types/index.ts';

interface ApprovalPanelProps {
  pendingApprovals: PendingApproval[];
  onApprove: (actionId: string) => void;
  onReject: (actionId: string) => void;
}

/**
 * Displays pending approval requests from the backend's human-in-the-loop
 * security model.  Each action shows a description and approve/reject buttons.
 */
export function ApprovalPanel({ pendingApprovals, onApprove, onReject }: ApprovalPanelProps) {
  if (pendingApprovals.length === 0) {
    return (
      <div className="p-4 text-center text-gray-600 text-sm">
        No pending approvals.
      </div>
    );
  }

  return (
    <div className="space-y-3 p-4" role="region" aria-label="Pending approvals">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-amber-400 mb-2">
        Pending Approvals ({pendingApprovals.length})
      </h3>
      {pendingApprovals.map((action) => (
        <div
          key={action.id}
          className="bg-[#1e2330] border border-amber-700/40 rounded-sm p-3"
          role="alert"
        >
          <div className="text-sm text-gray-200 mb-1 font-medium">
            {action.description}
          </div>
          <div className="text-xs text-gray-500 mb-3">
            Type: {action.type}
            {action.payload?.method ? ` | Method: ${action.payload.method}` : ''}
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => onApprove(action.id)}
              className="flex-1 bg-emerald-700 hover:bg-emerald-600 text-white text-xs px-3 py-1.5
                         rounded-sm transition-colors font-medium
                         focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-500"
              aria-label={`Approve: ${action.description}`}
            >
              Approve
            </button>
            <button
              onClick={() => onReject(action.id)}
              className="flex-1 bg-red-800 hover:bg-red-700 text-white text-xs px-3 py-1.5
                         rounded-sm transition-colors font-medium
                         focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-500"
              aria-label={`Reject: ${action.description}`}
            >
              Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
