import { Component } from 'react';

export default class ErrorBoundary extends Component {
  state = { error: null, info: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    this.setState({ error, info });
    console.error('[ErrorBoundary]', error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    const { error, info } = this.state;
    return (
      <div style={{ padding: 24, fontFamily: 'ui-monospace, monospace', fontSize: 12 }}>
        <div style={{ fontSize: 16, fontWeight: 500, color: '#b42318', marginBottom: 12 }}>
          ⚠ {error?.name || 'Error'}: {error?.message || String(error)}
        </div>
        <div style={{
          padding: 14, background: '#fdecea', border: '1px solid #f5c6ce', borderRadius: 8,
          whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.5,
          maxHeight: '45vh', overflow: 'auto', marginBottom: 12,
        }}>
          {error?.stack || '(无堆栈)'}
        </div>
        {info?.componentStack && (
          <div style={{
            padding: 14, background: '#f5f2ef', border: '1px solid rgba(0,0,0,0.08)', borderRadius: 8,
            whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.5,
            maxHeight: '30vh', overflow: 'auto', color: '#4e4e4e',
          }}>
            Component stack:{info.componentStack}
          </div>
        )}
        <button
          onClick={() => this.setState({ error: null, info: null })}
          style={{
            marginTop: 14, padding: '6px 14px', borderRadius: 6,
            border: '1px solid #bfbbb5', background: '#fff', cursor: 'pointer',
          }}
        >
          重试
        </button>
      </div>
    );
  }
}
