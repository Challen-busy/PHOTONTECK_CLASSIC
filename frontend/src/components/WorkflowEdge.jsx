import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath } from '@xyflow/react';

function getLabelOffset({ sourceX, sourceY, targetX, targetY, siblingIndex = 0, siblingCount = 1 }) {
  const dx = targetX - sourceX;
  const dy = targetY - sourceY;
  const spread = siblingCount > 1 ? (siblingIndex - (siblingCount - 1) / 2) * 22 : 0;

  if (Math.abs(dx) < 48 && Math.abs(dy) > 48) {
    return { x: (dy < 0 ? -70 : 70) + spread, y: 0 };
  }
  if (Math.abs(dy) < 48 && Math.abs(dx) > 48) {
    return { x: 0, y: (dx < 0 ? -24 : 24) + spread };
  }
  return {
    x: (dx >= 0 ? 44 : -44) + spread,
    y: dy >= 0 ? -18 : 18,
  };
}

export function decorateWorkflowEdges(edges) {
  const counts = {};
  edges.forEach(edge => {
    const key = `${edge.source}->${edge.target}`;
    counts[key] = (counts[key] || 0) + 1;
  });

  const seen = {};
  return edges.map(edge => {
    const key = `${edge.source}->${edge.target}`;
    const siblingIndex = seen[key] || 0;
    seen[key] = siblingIndex + 1;
    return {
      ...edge,
      type: 'workflow',
      data: {
        ...(edge.data || {}),
        siblingIndex,
        siblingCount: counts[key] || 1,
      },
    };
  });
}

export default function WorkflowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
  label,
  data,
}) {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 12,
    offset: 24,
  });
  const offset = getLabelOffset({
    sourceX,
    sourceY,
    targetX,
    targetY,
    siblingIndex: data?.siblingIndex || 0,
    siblingCount: data?.siblingCount || 1,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={style}
        interactionWidth={18}
      />
      {label && (
        <EdgeLabelRenderer>
          <div
            title={typeof label === 'string' ? label : undefined}
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX + offset.x}px, ${labelY + offset.y}px)`,
              pointerEvents: 'all',
              padding: '3px 8px',
              borderRadius: 6,
              border: '1px solid rgba(0,0,0,0.08)',
              background: 'rgba(255,255,255,0.98)',
              boxShadow: 'rgba(0,0,0,0.04) 0px 1px 2px',
              color: '#4e4e4e',
              fontSize: 11,
              lineHeight: '16px',
              maxWidth: 160,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              zIndex: 2,
            }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

