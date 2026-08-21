import React, { useState } from 'react';
import { IconCopy, IconCheck } from './Icons.tsx';

interface MarkdownViewProps {
  content: string;
}

export const MarkdownView: React.FC<MarkdownViewProps> = ({ content }) => {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const handleCopyCode = (codeText: string, index: number) => {
    navigator.clipboard.writeText(codeText);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  // Split content into code blocks and normal markdown segments
  const parseBlocks = (raw: string) => {
    const lines = raw.split('\n');
    const blocks: Array<{ type: 'code' | 'text' | 'table'; content: string; language?: string; rows?: string[][] }> = [];
    let inCode = false;
    let codeBuffer: string[] = [];
    let codeLang = '';
    let textBuffer: string[] = [];

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.trim().startsWith('```')) {
        if (inCode) {
          blocks.push({ type: 'code', content: codeBuffer.join('\n'), language: codeLang });
          codeBuffer = [];
          codeLang = '';
          inCode = false;
        } else {
          if (textBuffer.length > 0) {
            blocks.push({ type: 'text', content: textBuffer.join('\n') });
            textBuffer = [];
          }
          inCode = true;
          codeLang = line.trim().slice(3).trim();
        }
      } else if (inCode) {
        codeBuffer.push(line);
      } else {
        textBuffer.push(line);
      }
    }

    if (inCode && codeBuffer.length > 0) {
      blocks.push({ type: 'code', content: codeBuffer.join('\n'), language: codeLang });
    }
    if (textBuffer.length > 0) {
      blocks.push({ type: 'text', content: textBuffer.join('\n') });
    }

    return blocks;
  };

  const renderFormattedText = (text: string) => {
    const paragraphs = text.split('\n\n');
    return paragraphs.map((para, pIdx) => {
      const lines = para.split('\n');
      return (
        <div key={pIdx} style={{ marginBottom: pIdx < paragraphs.length - 1 ? '12px' : '0' }}>
          {lines.map((line, lIdx) => {
            const trimmed = line.trim();
            // Headers
            if (trimmed.startsWith('### ')) {
              return (
                <h3 key={lIdx} style={{ fontSize: '15px', fontWeight: 700, color: '#F2F2F2', margin: '14px 0 6px' }}>
                  {trimmed.replace(/^###\s+/, '')}
                </h3>
              );
            }
            if (trimmed.startsWith('## ')) {
              return (
                <h2 key={lIdx} style={{ fontSize: '16px', fontWeight: 700, color: '#F2F2F2', margin: '16px 0 8px', borderBottom: '1px solid #1E1E1E', paddingBottom: '4px' }}>
                  {trimmed.replace(/^##\s+/, '')}
                </h2>
              );
            }
            if (trimmed.startsWith('# ')) {
              return (
                <h1 key={lIdx} style={{ fontSize: '18px', fontWeight: 700, color: '#F2F2F2', margin: '18px 0 10px' }}>
                  {trimmed.replace(/^#\s+/, '')}
                </h1>
              );
            }

            // Bullet items
            if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
              const itemText = trimmed.replace(/^[-*]\s+/, '');
              return (
                <div key={lIdx} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', margin: '3px 0', paddingLeft: '4px' }}>
                  <span style={{ color: '#888888', lineHeight: '1.6' }}>•</span>
                  <span style={{ flex: 1, lineHeight: '1.6' }}>{renderInlineTokens(itemText)}</span>
                </div>
              );
            }

            // Numbered list
            const numMatch = trimmed.match(/^(\d+)\.\s+(.*)/);
            if (numMatch) {
              return (
                <div key={lIdx} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', margin: '3px 0', paddingLeft: '4px' }}>
                  <span style={{ color: '#888888', minWidth: '18px', lineHeight: '1.6', fontSize: '13px' }}>{numMatch[1]}.</span>
                  <span style={{ flex: 1, lineHeight: '1.6' }}>{renderInlineTokens(numMatch[2])}</span>
                </div>
              );
            }

            return (
              <div key={lIdx} style={{ lineHeight: '1.65', minHeight: trimmed ? 'auto' : '8px' }}>
                {renderInlineTokens(line)}
              </div>
            );
          })}
        </div>
      );
    });
  };

  const renderInlineTokens = (str: string) => {
    // Process **bold** and `code`
    const parts = str.split(/(\*\*.*?\*\*|`.*?`)/g);
    return parts.map((part, i) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={i} style={{ color: '#FFFFFF', fontWeight: 600 }}>{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith('`') && part.endsWith('`')) {
        return (
          <code key={i} style={{ background: '#16181D', border: '1px solid #22252B', padding: '1px 5px', borderRadius: '4px', fontSize: '12.5px', fontFamily: 'monospace', color: '#ECECEC' }}>
            {part.slice(1, -1)}
          </code>
        );
      }
      return part;
    });
  };

  const blocks = parseBlocks(content);

  return (
    <div style={{ color: '#F2F2F2', fontSize: '14px', lineHeight: '1.65', wordBreak: 'break-word' }}>
      {blocks.map((block, idx) => {
        if (block.type === 'code') {
          const isCopied = copiedIndex === idx;
          return (
            <div
              key={idx}
              style={{
                margin: '12px 0',
                background: '#0D0D0D',
                border: '1px solid #202020',
                borderRadius: '8px',
                overflow: 'hidden',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 12px', background: '#141414', borderBottom: '1px solid #202020', fontSize: '11px', color: '#888888' }}>
                <span>{block.language || 'code'}</span>
                <button
                  onClick={() => handleCopyCode(block.content, idx)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: isCopied ? '#4ADE80' : '#8E8E8E',
                    fontSize: '11px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    cursor: 'pointer',
                    padding: '2px 6px',
                    borderRadius: '4px',
                  }}
                  onMouseEnter={(e) => { if (!isCopied) e.currentTarget.style.color = '#F2F2F2'; }}
                  onMouseLeave={(e) => { if (!isCopied) e.currentTarget.style.color = '#8E8E8E'; }}
                >
                  {isCopied ? <IconCheck size={12} /> : <IconCopy size={12} />}
                  <span>{isCopied ? 'Copied' : 'Copy'}</span>
                </button>
              </div>
              <pre style={{ margin: 0, padding: '12px 14px', overflowX: 'auto', fontSize: '13px', lineHeight: '1.5', fontFamily: 'Consolas, Monaco, "Courier New", monospace', color: '#F2F2F2' }}>
                <code>{block.content}</code>
              </pre>
            </div>
          );
        }
        return <div key={idx}>{renderFormattedText(block.content)}</div>;
      })}
    </div>
  );
};
