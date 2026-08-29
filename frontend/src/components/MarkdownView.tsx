import React, { useState } from 'react';
import { IconCopy, IconCheck } from './Icons.tsx';

interface MarkdownViewProps { content: string; }
type Block = { type: 'code' | 'text' | 'table'; content: string; language?: string; rows?: string[][]; align?: Array<'left' | 'center' | 'right'> };

function splitTableRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  return trimmed.split(/(?<!\\)\|/).map((cell) => cell.trim().replace(/\\\|/g, '|'));
}

function parseAlignment(cell: string): 'left' | 'center' | 'right' | null {
  const value = cell.trim();
  if (!/^:?-{3,}:?$/.test(value)) return null;
  if (value.startsWith(':') && value.endsWith(':')) return 'center';
  if (value.endsWith(':')) return 'right';
  return 'left';
}

function isTableSeparator(line: string): boolean {
  const cells = splitTableRow(line);
  return cells.length > 1 && cells.every((cell) => parseAlignment(cell) !== null);
}

export const MarkdownView: React.FC<MarkdownViewProps> = ({ content }) => {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const handleCopyCode = (codeText: string, index: number) => {
    navigator.clipboard.writeText(codeText);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const parseBlocks = (raw: string): Block[] => {
    const lines = raw.split('\n');
    const blocks: Block[] = [];
    let inCode = false;
    let codeBuffer: string[] = [];
    let codeLang = '';
    let textBuffer: string[] = [];

    const flushText = () => {
      if (textBuffer.length) {
        blocks.push({ type: 'text', content: textBuffer.join('\n') });
        textBuffer = [];
      }
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
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
        continue;
      }
      if (inCode) {
        codeBuffer.push(line);
        continue;
      }

      // GitHub-flavoured table: header row followed by separator row.
      if (i + 1 < lines.length && line.includes('|') && isTableSeparator(lines[i + 1])) {
        flushText();
        const header = splitTableRow(line);
        const separator = splitTableRow(lines[i + 1]);
        const align = separator.map((cell) => parseAlignment(cell) || 'left');
        const rows: string[][] = [header];
        i += 2;
        while (i < lines.length && lines[i].includes('|') && lines[i].trim()) {
          rows.push(splitTableRow(lines[i]));
          i += 1;
        }
        i -= 1;
        blocks.push({ type: 'table', content: '', rows, align });
        continue;
      }

      textBuffer.push(line);
    }

    if (inCode) {
      // Unterminated code fence remains visible as code instead of disappearing.
      blocks.push({ type: 'code', content: codeBuffer.join('\n'), language: codeLang });
    }
    flushText();
    return blocks;
  };

  const renderInlineTokens = (str: string) => {
    const parts = str.split(/(\*\*.*?\*\*|`.*?`)/g);
    return parts.map((part, i) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={i} style={{ color: '#FFFFFF', fontWeight: 600 }}>{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith('`') && part.endsWith('`')) {
        return <code key={i} style={{ background: '#16181D', border: '1px solid #22252B', padding: '1px 5px', borderRadius: '4px', fontSize: '12.5px', fontFamily: 'monospace', color: '#ECECEC' }}>{part.slice(1, -1)}</code>;
      }
      return part;
    });
  };

  const renderFormattedText = (text: string) => text.split('\n\n').map((para, pIdx, paragraphs) => (
    <div key={pIdx} style={{ marginBottom: pIdx < paragraphs.length - 1 ? '12px' : 0 }}>
      {para.split('\n').map((line, lIdx) => {
        const trimmed = line.trim();
        if (trimmed.startsWith('### ')) return <h3 key={lIdx} style={{ fontSize: '15px', fontWeight: 700, color: '#F2F2F2', margin: '14px 0 6px' }}>{renderInlineTokens(trimmed.replace(/^###\s+/, ''))}</h3>;
        if (trimmed.startsWith('## ')) return <h2 key={lIdx} style={{ fontSize: '16px', fontWeight: 700, color: '#F2F2F2', margin: '16px 0 8px', borderBottom: '1px solid #1E1E1E', paddingBottom: '4px' }}>{renderInlineTokens(trimmed.replace(/^##\s+/, ''))}</h2>;
        if (trimmed.startsWith('# ')) return <h1 key={lIdx} style={{ fontSize: '18px', fontWeight: 700, color: '#F2F2F2', margin: '18px 0 10px' }}>{renderInlineTokens(trimmed.replace(/^#\s+/, ''))}</h1>;
        if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
          const itemText = trimmed.replace(/^[-*]\s+/, '');
          return <div key={lIdx} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', margin: '3px 0', paddingLeft: '4px' }}><span style={{ color: '#888888', lineHeight: '1.6' }}>•</span><span style={{ flex: 1, lineHeight: '1.6' }}>{renderInlineTokens(itemText)}</span></div>;
        }
        const numMatch = trimmed.match(/^(\d+)\.\s+(.*)/);
        if (numMatch) return <div key={lIdx} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', margin: '3px 0', paddingLeft: '4px' }}><span style={{ color: '#888888', minWidth: '18px', lineHeight: '1.6', fontSize: '13px' }}>{numMatch[1]}.</span><span style={{ flex: 1, lineHeight: '1.6' }}>{renderInlineTokens(numMatch[2])}</span></div>;
        return <div key={lIdx} style={{ lineHeight: '1.65', minHeight: trimmed ? 'auto' : '8px' }}>{renderInlineTokens(line)}</div>;
      })}
    </div>
  ));

  const blocks = parseBlocks(content);

  return <div style={{ color: '#F2F2F2', fontSize: '14px', lineHeight: '1.65', wordBreak: 'break-word' }}>
    {blocks.map((block, idx) => {
      if (block.type === 'table' && block.rows?.length) {
        const [header, ...body] = block.rows;
        return <div key={idx} style={{ overflowX: 'auto', margin: '12px 0', border: '1px solid #242424', borderRadius: '8px' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '420px' }}>
            <thead><tr>{header.map((cell, cellIdx) => <th key={cellIdx} style={{ textAlign: block.align?.[cellIdx] || 'left', padding: '8px 10px', background: '#141414', borderBottom: '1px solid #282828', fontWeight: 650 }}>{renderInlineTokens(cell)}</th>)}</tr></thead>
            <tbody>{body.map((row, rowIdx) => <tr key={rowIdx}>{header.map((_, cellIdx) => <td key={cellIdx} style={{ textAlign: block.align?.[cellIdx] || 'left', padding: '8px 10px', borderTop: rowIdx === 0 ? 'none' : '1px solid #1B1B1B', verticalAlign: 'top' }}>{renderInlineTokens(row[cellIdx] || '')}</td>)}</tr>)}</tbody>
          </table>
        </div>;
      }
      if (block.type === 'code') {
        const isCopied = copiedIndex === idx;
        return <div key={idx} style={{ margin: '12px 0', background: '#0D0D0D', border: '1px solid #202020', borderRadius: '8px', overflow: 'hidden' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 12px', background: '#141414', borderBottom: '1px solid #202020', fontSize: '11px', color: '#888888' }}>
            <span>{block.language || 'code'}</span>
            <button onClick={() => handleCopyCode(block.content, idx)} style={{ background: 'transparent', border: 'none', color: isCopied ? '#4ADE80' : '#8E8E8E', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer', padding: '2px 6px', borderRadius: '4px' }}>{isCopied ? <IconCheck size={12} /> : <IconCopy size={12} />}<span>{isCopied ? 'Copied' : 'Copy'}</span></button>
          </div>
          <pre style={{ margin: 0, padding: '12px 14px', overflowX: 'auto', fontSize: '13px', lineHeight: '1.5', fontFamily: 'Consolas, Monaco, "Courier New", monospace', color: '#F2F2F2' }}><code>{block.content}</code></pre>
        </div>;
      }
      return <div key={idx}>{renderFormattedText(block.content)}</div>;
    })}
  </div>;
};
