import React, { useState } from 'react';
import { IconCopy, IconCheck } from './Icons.tsx';

interface MarkdownViewProps {
  content: string;
}

type MarkdownBlock = {
  type: 'code' | 'text';
  content: string;
  language?: string;
};

export const MarkdownView: React.FC<MarkdownViewProps> = ({ content }) => {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const handleCopyCode = (codeText: string, index: number) => {
    navigator.clipboard.writeText(codeText);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const parseBlocks = (raw: string): MarkdownBlock[] => {
    const lines = raw.split('\n');
    const blocks: MarkdownBlock[] = [];
    let inCode = false;
    let codeBuffer: string[] = [];
    let codeLang = '';
    let textBuffer: string[] = [];

    const flushText = () => {
      if (textBuffer.length > 0) {
        blocks.push({ type: 'text', content: textBuffer.join('\n') });
        textBuffer = [];
      }
    };

    for (const line of lines) {
      if (line.trim().startsWith('```')) {
        if (inCode) {
          blocks.push({ type: 'code', content: codeBuffer.join('\n'), language: codeLang });
          codeBuffer = [];
          codeLang = '';
          inCode = false;
        } else {
          flushText();
          inCode = true;
          codeLang = line.trim().slice(3).trim();
        }
      } else if (inCode) {
        codeBuffer.push(line);
      } else {
        textBuffer.push(line);
      }
    }

    if (inCode) {
      // Unclosed fences remain code, never interpreted as HTML/Markdown structure.
      blocks.push({ type: 'code', content: codeBuffer.join('\n'), language: codeLang });
    }
    flushText();
    return blocks;
  };

  const renderInlineTokens = (str: string) => {
    // React renders text safely; raw HTML is never executed. Support only the
    // bounded inline syntax we actually need in the desktop chat.
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

  const splitTableRow = (line: string): string[] => {
    const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
    return trimmed.split('|').map((cell) => cell.trim());
  };

  const isTableSeparator = (line: string): boolean => {
    const cells = splitTableRow(line);
    return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
  };

  const renderTable = (header: string[], rows: string[][], key: string) => (
    <div key={key} style={{ overflowX: 'auto', margin: '12px 0' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', minWidth: '420px' }}>
        <thead>
          <tr>
            {header.map((cell, idx) => (
              <th key={idx} style={{ textAlign: 'left', padding: '8px 10px', border: '1px solid #2A2A2A', background: '#151515', fontWeight: 650, verticalAlign: 'top' }}>
                {renderInlineTokens(cell)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rIdx) => (
            <tr key={rIdx}>
              {header.map((_, cIdx) => (
                <td key={cIdx} style={{ padding: '8px 10px', border: '1px solid #262626', verticalAlign: 'top', lineHeight: '1.55' }}>
                  {renderInlineTokens(row[cIdx] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const renderNormalLine = (line: string, key: string) => {
    const trimmed = line.trim();
    if (!trimmed) return <div key={key} style={{ height: '8px' }} />;

    if (trimmed.startsWith('### ')) {
      return <h3 key={key} style={{ fontSize: '15px', fontWeight: 700, color: '#F2F2F2', margin: '14px 0 6px' }}>{renderInlineTokens(trimmed.replace(/^###\s+/, ''))}</h3>;
    }
    if (trimmed.startsWith('## ')) {
      return <h2 key={key} style={{ fontSize: '16px', fontWeight: 700, color: '#F2F2F2', margin: '16px 0 8px', borderBottom: '1px solid #1E1E1E', paddingBottom: '4px' }}>{renderInlineTokens(trimmed.replace(/^##\s+/, ''))}</h2>;
    }
    if (trimmed.startsWith('# ')) {
      return <h1 key={key} style={{ fontSize: '18px', fontWeight: 700, color: '#F2F2F2', margin: '18px 0 10px' }}>{renderInlineTokens(trimmed.replace(/^#\s+/, ''))}</h1>;
    }

    if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      const itemText = trimmed.replace(/^[-*]\s+/, '');
      return (
        <div key={key} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', margin: '3px 0', paddingLeft: '4px' }}>
          <span style={{ color: '#888888', lineHeight: '1.6' }}>•</span>
          <span style={{ flex: 1, lineHeight: '1.6' }}>{renderInlineTokens(itemText)}</span>
        </div>
      );
    }

    const numMatch = trimmed.match(/^(\d+)\.\s+(.*)/);
    if (numMatch) {
      return (
        <div key={key} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', margin: '3px 0', paddingLeft: '4px' }}>
          <span style={{ color: '#888888', minWidth: '18px', lineHeight: '1.6', fontSize: '13px' }}>{numMatch[1]}.</span>
          <span style={{ flex: 1, lineHeight: '1.6' }}>{renderInlineTokens(numMatch[2])}</span>
        </div>
      );
    }

    return <div key={key} style={{ lineHeight: '1.65' }}>{renderInlineTokens(line)}</div>;
  };

  const renderFormattedText = (text: string) => {
    const lines = text.split('\n');
    const rendered: React.ReactNode[] = [];

    for (let i = 0; i < lines.length;) {
      const line = lines[i];
      const next = lines[i + 1];
      // GFM table: header row immediately followed by a --- separator row.
      if (line.includes('|') && next !== undefined && isTableSeparator(next)) {
        const header = splitTableRow(line);
        const rows: string[][] = [];
        i += 2;
        while (i < lines.length && lines[i].includes('|') && lines[i].trim() !== '') {
          const row = splitTableRow(lines[i]);
          // Avoid accidentally swallowing prose containing a single pipe.
          if (row.length < 2) break;
          rows.push(row);
          i += 1;
        }
        rendered.push(renderTable(header, rows, `table-${i}`));
        continue;
      }

      rendered.push(renderNormalLine(line, `line-${i}`));
      i += 1;
    }
    return rendered;
  };

  const blocks = parseBlocks(content);

  return (
    <div style={{ color: '#F2F2F2', fontSize: '14px', lineHeight: '1.65', wordBreak: 'break-word' }}>
      {blocks.map((block, idx) => {
        if (block.type === 'code') {
          const isCopied = copiedIndex === idx;
          return (
            <div key={idx} style={{ margin: '12px 0', background: '#0D0D0D', border: '1px solid #202020', borderRadius: '8px', overflow: 'hidden' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 12px', background: '#141414', borderBottom: '1px solid #202020', fontSize: '11px', color: '#888888' }}>
                <span>{block.language || 'code'}</span>
                <button
                  onClick={() => handleCopyCode(block.content, idx)}
                  style={{ background: 'transparent', border: 'none', color: isCopied ? '#4ADE80' : '#8E8E8E', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer', padding: '2px 6px', borderRadius: '4px' }}
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
