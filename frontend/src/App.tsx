import React, { useState, useEffect, useRef } from 'react';
import brandLogo from './assets/logo.png';
import { MarkdownView } from './components/MarkdownView.tsx';
import { ModelSettingsView } from './components/ModelSettingsView.tsx';
import {
  IconPlus,
  IconClock,
  IconFolder,
  IconBuilding,
  IconLayout,
  IconBook,
  IconShieldCheck,
  IconPlug,
  IconReceipt,
  IconSettings,
  IconUser,
  IconEdit,
  IconArchive,
  IconTrash,
  IconSend,
  IconMonitor,
  IconFileText,
  IconClipboard,
  IconLink,
  IconChevronRight,
  IconChevronLeft,
  IconPaperclip,
  IconClose,
  IconCopy,
  IconRotateCw,
  IconCheck,
  IconAlertCircle,
} from './components/Icons.tsx';
import {
  ConnectorHealthItem,
  BusinessWorkspace,
  PendingApprovalItem,
  ExecutionReceiptItem,
} from './types/index.ts';
import { apiFetch } from './api/client.ts';
import { streamChatTurn, RuntimeProgressData } from './api/streaming.ts';
import {
  canSubmitTurn,
  createAssistantPlaceholder,
  createInitialWorkflowStages,
  createDefaultAgentStates,
  applyDeltaToSessions,
  applyProgressToWorkflow,
  applyProgressToAgents,
  applyTerminalCompleteToSessions,
  applyTerminalErrorToSessions,
  applyTerminalErrorToStages,
  WorkflowStageState,
} from './chat/streamState.ts';

const API_BASE = '';

interface ChatAttachmentItem {
  attachment_id?: string;
  filename_or_url: string;
  type: string;
  content: string;
}

interface ChatMessageItem {
  message_id: string;
  role: 'user' | 'assistant' | 'system';
  sender_name: string;
  content: string;
  run_id?: string;
  status?: string;
  attachments?: Array<{
    attachment_id: string;
    filename_or_url: string;
    attachment_type: string;
  }>;
}

interface ChatSessionItem {
  chat_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  status: string;
  optional_project_id?: string | null;
  optional_business_id?: string | null;
  messages: ChatMessageItem[];
}

interface ProjectItem {
  project_id: string;
  project_name: string;
  description: string;
  chat_ids: string[];
}

function classifyErrorMessage(errOrStatus: any, fallback = 'Lỗi không xác định'): string {
  if (typeof errOrStatus === 'number') {
    if (errOrStatus === 401) return 'Lỗi xác thực phiên cục bộ (BACKEND_UNAUTHENTICATED).';
    if (errOrStatus === 502 || errOrStatus === 503 || errOrStatus === 504) return 'Dịch vụ backend tạm thời không phản hồi (BACKEND_UNHEALTHY).';
    if (errOrStatus >= 500) return 'Lỗi dịch vụ nội bộ (BACKEND_ERROR).';
  }
  if (typeof errOrStatus === 'string') {
    if (errOrStatus.includes('BACKEND_PROCESS_TERMINATED')) {
      return 'Tiến trình backend đã dừng đột ngột (BACKEND_PROCESS_TERMINATED). Vui lòng khởi động lại ứng dụng.';
    }
    if (errOrStatus.includes('BACKEND_UNAVAILABLE') || errOrStatus.includes('CONNECTION_FAILED')) {
      return 'Không thể kết nối đến dịch vụ backend cục bộ (BACKEND_UNAVAILABLE).';
    }
    if (errOrStatus.includes('BACKEND_UNAUTHENTICATED')) {
      return 'Lỗi xác thực phiên cục bộ (BACKEND_UNAUTHENTICATED).';
    }
    if (errOrStatus.includes('MODEL_PROVIDER') || errOrStatus.includes('provider') || errOrStatus.includes('API key')) {
      return `Lỗi kết nối mô hình AI (MODEL_PROVIDER_FAILURE): ${errOrStatus}`;
    }
    return errOrStatus;
  }
  if (errOrStatus instanceof Error) {
    return classifyErrorMessage(errOrStatus.message, fallback);
  }
  return fallback;
}

export default function App() {
  const [activeView, setActiveView] = useState<'chat' | 'dashboard' | 'brands' | 'projects' | 'knowledge' | 'memory' | 'approvals' | 'connections' | 'activity' | 'settings'>('chat');
  const [backendState, setBackendState] = useState<'STARTING_BACKEND' | 'BACKEND_READY' | 'BACKEND_FAILED'>('STARTING_BACKEND');
  const [backendErrorDetail, setBackendErrorDetail] = useState<string>('');
  const [chatSessions, setChatSessions] = useState<ChatSessionItem[]>([]);
  const [activeChatId, setActiveChatId] = useState<string>('');
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [workspaces, setWorkspaces] = useState<BusinessWorkspace[]>([]);
  const [connectorHealth, setConnectorHealth] = useState<Record<string, ConnectorHealthItem>>({});
  const [pendingApprovals, setPendingApprovals] = useState<PendingApprovalItem[]>([]);
  const [receipts, setReceipts] = useState<ExecutionReceiptItem[]>([]);

  // Chat Composer & Attachment Menu State
  const [chatInput, setChatInput] = useState<string>('');
  const [attachments, setAttachments] = useState<ChatAttachmentItem[]>([]);
  const [isProcessing, setIsProcessing] = useState<boolean>(false);
  const [agentProgress, setAgentProgress] = useState<string>('');
  const [showRightDrawer, setShowRightDrawer] = useState<boolean>(true);
  const [showAttachmentMenu, setShowAttachmentMenu] = useState<boolean>(false);

  // Message Action States: Copy feedback & Inline Edit
  const [copiedMsgId, setCopiedMsgId] = useState<string | null>(null);
  const [editingMsgId, setEditingMsgId] = useState<string | null>(null);
  const [editingMsgContent, setEditingMsgContent] = useState<string>('');

  // Modals & UI States
  const [showPasteModal, setShowPasteModal] = useState<boolean>(false);
  const [pasteModalTitle, setPasteModalTitle] = useState<string>('Pasted Note');
  const [pasteModalContent, setPasteModalContent] = useState<string>('');
  const [editingChatId, setEditingChatId] = useState<string | null>(null);
  const [editChatTitle, setEditChatTitle] = useState<string>('');
  const [urlModalOpen, setUrlModalOpen] = useState<boolean>(false);
  const [urlInput, setUrlInput] = useState<string>('');

  // Agent live states (5 Permanent Agents)
  const [agentStates, setAgentStates] = useState<Record<string, any>>(
    createDefaultAgentStates()
  );
  // 6 Workflow Stages (CMO_INITIAL, INTELLIGENCE, STRATEGIST, CREATIVE, PERFORMANCE, FINAL_CMO)
  const [workflowStages, setWorkflowStages] = useState<WorkflowStageState[]>(
    createInitialWorkflowStages()
  );

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const editMsgTextareaRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const computerFileInputRef = useRef<HTMLInputElement>(null);
  const attachmentMenuRef = useRef<HTMLDivElement>(null);

  const fetchCoreData = async () => {
    try {
      const [sessRes, projRes, wsRes, connRes, appRes, recRes] = await Promise.allSettled([
        apiFetch(`${API_BASE}/api/chat/sessions`),
        apiFetch(`${API_BASE}/api/projects`),
        apiFetch(`${API_BASE}/api/business_workspaces`),
        apiFetch(`${API_BASE}/api/connectors/health`),
        apiFetch(`${API_BASE}/api/approvals`),
        apiFetch(`${API_BASE}/api/execution_receipts`),
      ]);

      if (sessRes.status === 'fulfilled' && sessRes.value.ok) {
        const data = await sessRes.value.json();
        const items = data.sessions || [];
        setChatSessions(items);
        if (items.length > 0 && !activeChatId) {
          setActiveChatId(items[0].chat_id);
        }
      }
      if (projRes.status === 'fulfilled' && projRes.value.ok) {
        const data = await projRes.value.json();
        setProjects(data.projects || []);
      }
      if (wsRes.status === 'fulfilled' && wsRes.value.ok) {
        const data = await wsRes.value.json();
        setWorkspaces(data.workspaces || []);
      }
      if (connRes.status === 'fulfilled' && connRes.value.ok) {
        const data = await connRes.value.json();
        setConnectorHealth(data.connectors || {});
      }
      if (appRes.status === 'fulfilled' && appRes.value.ok) {
        const data = await appRes.value.json();
        setPendingApprovals(data.approvals || []);
      }
      if (recRes.status === 'fulfilled' && recRes.value.ok) {
        const data = await recRes.value.json();
        setReceipts(data.receipts || []);
      }
    } catch (e) {
      console.warn('Background core data refresh skipped:', e);
    }
  };

  useEffect(() => {
    const initApp = async () => {
      try {
        const res = await apiFetch(`${API_BASE}/api/health`);
        if (res.ok) {
          setBackendState('BACKEND_READY');
          fetchCoreData();
        } else {
          setBackendState('BACKEND_FAILED');
          setBackendErrorDetail(`Backend health check failed (${res.status})`);
        }
      } catch (err: any) {
        setBackendState('BACKEND_FAILED');
        setBackendErrorDetail(classifyErrorMessage(err, 'Cannot connect to local backend service.'));
      }
    };
    initApp();
  }, []);

  useEffect(() => {
    fetchCoreData();
    const interval = setInterval(fetchCoreData, 8000);
    return () => clearInterval(interval);
  }, []);

  // Close attachment menu on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (attachmentMenuRef.current && !attachmentMenuRef.current.contains(e.target as Node)) {
        setShowAttachmentMenu(false);
      }
    };
    if (showAttachmentMenu) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showAttachmentMenu]);

  const scrollToBottom = (smooth = true) => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto' });
    }
  };

  useEffect(() => {
    scrollToBottom(false);
  }, [activeChatId]);

  const activeChat = chatSessions.find((s) => s.chat_id === activeChatId) || null;

  // Auto-resize textarea
  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setChatInput(e.target.value);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  };

  // Keyboard shortcut: Enter = send, Shift+Enter = newline
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const handleCopyText = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedMsgId(id);
    setTimeout(() => setCopiedMsgId(null), 2000);
  };

  const handleCreateNewChat = () => {
    setActiveChatId('');
    setActiveView('chat');
    setAttachments([]);
    setChatInput('');
    setEditingMsgId(null);
    resetAgentStates();
    setTimeout(() => textareaRef.current?.focus(), 50);
  };

  const handleRenameChat = async (chatId: string, newTitle: string) => {
    if (!newTitle.trim()) return;
    try {
      await apiFetch(`${API_BASE}/api/chat/sessions/${chatId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle.trim() }),
      });
    } catch (e) {
      console.warn('Rename error:', e);
    }
    setChatSessions((prev) =>
      prev.map((s) => (s.chat_id === chatId ? { ...s, title: newTitle.trim() } : s))
    );
    setEditingChatId(null);
  };

  const handleArchiveChat = async (chatId: string) => {
    try {
      await apiFetch(`${API_BASE}/api/chat/sessions/${chatId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'ARCHIVED' }),
      });
    } catch (e) {
      console.warn('Archive error:', e);
    }
    setChatSessions((prev) =>
      prev.map((s) => (s.chat_id === chatId ? { ...s, status: 'ARCHIVED' } : s))
    );
  };

  const handleDeleteChat = async (chatId: string) => {
    try {
      await apiFetch(`${API_BASE}/api/chat/sessions/${chatId}`, {
        method: 'DELETE',
      });
    } catch (e) {
      console.warn('Delete error:', e);
    }
    setChatSessions((prev) => {
      const remaining = prev.filter((s) => s.chat_id !== chatId);
      if (activeChatId === chatId) {
        setActiveChatId(remaining.length > 0 ? remaining[0].chat_id : '');
      }
      return remaining;
    });
  };
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    const file = files[0];
    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      const newAtt: ChatAttachmentItem = {
        attachment_id: `ATT-${Date.now()}`,
        filename_or_url: file.name,
        type: file.type || 'text/plain',
        content: content || '',
      };
      setAttachments((prev) => [...prev, newAtt]);
    };
    reader.readAsText(file);
    e.target.value = '';
    setShowAttachmentMenu(false);
  };


  const handleSaveUrlAttachment = () => {
    if (!urlInput.trim()) return;
    const newAtt: ChatAttachmentItem = {
      attachment_id: `ATT-URL-${Date.now()}`,
      filename_or_url: urlInput.trim(),
      type: 'url_reference',
      content: urlInput.trim(),
    };
    setAttachments((prev) => [...prev, newAtt]);
    setUrlModalOpen(false);
    setUrlInput('');
  };

  const handleSavePastedText = () => {
    if (!pasteModalContent.trim()) return;
    const title = pasteModalTitle.trim() || 'Pasted Note';
    const noteAtt: ChatAttachmentItem = {
      attachment_id: `ATT-NOTE-${Date.now()}`,
      filename_or_url: `${title}.txt`,
      type: 'text/plain',
      content: pasteModalContent,
    };
    setAttachments((prev) => [...prev, noteAtt]);
    setPasteModalContent('');
    setShowPasteModal(false);
    setShowAttachmentMenu(false);
  };

  const resetAgentStates = () => {
    setAgentStates(createDefaultAgentStates());
    setWorkflowStages(createInitialWorkflowStages());
  };

  const handleSendMessage = async () => {
    if (!canSubmitTurn(isProcessing, chatInput, attachments.length)) return;

    const textToSend = chatInput.trim();
    const sentAttachments = [...attachments];
    const userMsgId = `MSG-U-${Date.now()}`;
    const assistantMsgId = `MSG-A-${Date.now()}`;

    const userMsg: ChatMessageItem = {
      message_id: userMsgId,
      role: 'user',
      sender_name: 'You',
      content: textToSend,
      attachments: sentAttachments.map((a) => ({
        attachment_id: a.attachment_id || `ATT-${Date.now()}`,
        filename_or_url: a.filename_or_url,
        attachment_type: a.type,
      })),
    };

    const assistantPlaceholder = createAssistantPlaceholder(assistantMsgId);

    setChatInput('');
    setAttachments([]);
    if (textareaRef.current) textareaRef.current.style.height = 'auto';

    setIsProcessing(true);
    setAgentProgress('Connecting...');
    setWorkflowStages(createInitialWorkflowStages());

    let turnChatId = activeChatId;
    let path = '';
    let body: any = { content: textToSend, attachments: sentAttachments };

    // Flow 1: Lazy Auto-Creation on First Message
    if (!turnChatId) {
      const pendingTitle = textToSend.split('\n')[0].substring(0, 30) || (sentAttachments[0]?.filename_or_url || 'New Chat');
      const tempChatId = `CHAT-TEMP-${Date.now()}`;
      turnChatId = tempChatId;

      const tempSession: ChatSessionItem = {
        chat_id: tempChatId,
        title: pendingTitle,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        status: 'ACTIVE',
        messages: [userMsg, assistantPlaceholder],
      };

      setChatSessions((prev) => [tempSession, ...prev]);
      setActiveChatId(tempChatId);
      path = '/api/chat/stream';
    } else {
      // Flow 2: Existing Active Chat Turn
      setChatSessions((prev) =>
        prev.map((s) =>
          s.chat_id === turnChatId
            ? {
                ...s,
                messages: [...s.messages, userMsg, assistantPlaceholder],
                updated_at: new Date().toISOString(),
              }
            : s
        )
      );
      path = `/api/chat/sessions/${turnChatId}/stream`;
    }
    setTimeout(() => scrollToBottom(true), 50);

    let assignedChatId = turnChatId;

    await streamChatTurn({
      path,
      body,
      onProgress: (progress: RuntimeProgressData) => {
        if (progress.message) {
          setAgentProgress(progress.message);
        }
        setWorkflowStages((prev) => applyProgressToWorkflow(prev, progress));
        setAgentStates((prev) => applyProgressToAgents(prev, progress));
      },
      onDelta: (delta) => {
        setChatSessions((prev) =>
          applyDeltaToSessions(prev, [turnChatId, assignedChatId], assistantMsgId, delta.content)
        );
        scrollToBottom(true);
      },
      onComplete: (complete) => {
        let finalChatId = assignedChatId;
        setChatSessions((prev) => {
          const res = applyTerminalCompleteToSessions(
            prev,
            turnChatId,
            assignedChatId,
            assistantMsgId,
            complete
          );
          finalChatId = res.finalChatId;
          assignedChatId = res.finalChatId;
          return res.sessions;
        });
        if (finalChatId && finalChatId !== activeChatId) {
          setActiveChatId(finalChatId);
        }
        setIsProcessing(false);
        setAgentProgress('');
        fetchCoreData();
      },
      onError: (err) => {
        const errorMsg = classifyErrorMessage(err.message || err.code, 'Không thể nhận phản hồi từ backend.');
        setChatSessions((prev) =>
          applyTerminalErrorToSessions(prev, [turnChatId, assignedChatId], assistantMsgId, errorMsg)
        );
        setWorkflowStages((prev) => applyTerminalErrorToStages(prev));
        setIsProcessing(false);
        setAgentProgress('');
        fetchCoreData();
      },
    });
  };

  // Edit User Message & Resend
  const handleStartEditMessage = (msg: ChatMessageItem) => {
    setEditingMsgId(msg.message_id);
    setEditingMsgContent(msg.content);
    setTimeout(() => {
      if (editMsgTextareaRef.current) {
        editMsgTextareaRef.current.focus();
        editMsgTextareaRef.current.style.height = 'auto';
        editMsgTextareaRef.current.style.height = `${editMsgTextareaRef.current.scrollHeight}px`;
      }
    }, 50);
  };

  const handleCancelEditMessage = () => {
    setEditingMsgId(null);
    setEditingMsgContent('');
  };

  const handleSendEditedMessage = async (msgId: string) => {
    if (!editingMsgContent.trim() || !activeChatId) return;
    const newContent = editingMsgContent.trim();
    setEditingMsgId(null);
    setIsProcessing(true);
    setAgentProgress('Processing edited message...');

    // Optimistically update message in UI
    setChatSessions((prev) =>
      prev.map((s) =>
        s.chat_id === activeChatId
          ? {
              ...s,
              messages: s.messages.map((m) =>
                m.message_id === msgId ? { ...m, content: newContent } : m
              ),
            }
          : s
      )
    );

    try {
      const res = await apiFetch(`${API_BASE}/api/chat/sessions/${activeChatId}/messages/${msgId}/edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: newContent, auto_execute: true }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.message) {
          setChatSessions((prev) =>
            prev.map((s) =>
              s.chat_id === activeChatId
                ? {
                    ...s,
                    messages: [...s.messages, data.message],
                    updated_at: new Date().toISOString(),
                  }
                : s
            )
          );
        }
      }
    } catch (e) {
      console.warn('Edit send error:', e);
    }

    setIsProcessing(false);
    setAgentProgress('');
    setTimeout(() => scrollToBottom(true), 100);
    fetchCoreData();
  };

  // Regenerate Response
  const handleRegenerate = async (msgId?: string) => {
    if (!activeChatId || isProcessing) return;
    setIsProcessing(true);
    setAgentProgress('Regenerating response...');

    try {
      const endpoint = msgId
        ? `${API_BASE}/api/chat/sessions/${activeChatId}/messages/${msgId}/regenerate`
        : `${API_BASE}/api/chat/sessions/${activeChatId}/regenerate`;

      const res = await apiFetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_execute: true }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.message) {
          setChatSessions((prev) =>
            prev.map((s) =>
              s.chat_id === activeChatId
                ? {
                    ...s,
                    messages: [...s.messages, data.message],
                    updated_at: new Date().toISOString(),
                  }
                : s
            )
          );
        }
      }
    } catch (e) {
      console.warn('Regenerate error:', e);
    }

    setIsProcessing(false);
    setAgentProgress('');
    setTimeout(() => scrollToBottom(true), 100);
    fetchCoreData();
  };

  // Retry Failed Request
  const handleRetry = async () => {
    if (!activeChatId || isProcessing) return;
    setIsProcessing(true);
    setAgentProgress('Retrying request...');

    try {
      const res = await apiFetch(`${API_BASE}/api/chat/sessions/${activeChatId}/retry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_execute: true }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.message) {
          setChatSessions((prev) =>
            prev.map((s) =>
              s.chat_id === activeChatId
                ? {
                    ...s,
                    // Remove error placeholder and append new response
                    messages: [
                      ...s.messages.filter((m) => m.status !== 'ERROR'),
                      data.message,
                    ],
                    updated_at: new Date().toISOString(),
                  }
                : s
            )
          );
        }
      }
    } catch (e) {
      console.warn('Retry error:', e);
    }

    setIsProcessing(false);
    setAgentProgress('');
    setTimeout(() => scrollToBottom(true), 100);
    fetchCoreData();
  };

  return (
    <div style={{ display: 'flex', width: '100vw', height: '100vh', background: '#050505', color: '#F2F2F2', fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif', overflow: 'hidden' }}>
      {/* Hidden File Inputs */}
      <input type="file" ref={fileInputRef} onChange={handleFileUpload} multiple style={{ display: 'none' }} />
      <input type="file" ref={computerFileInputRef} onChange={handleFileUpload} multiple style={{ display: 'none' }} />

      {/* ========================================================
          LEFT SIDEBAR (#080808)
      ======================================================== */}
      <aside style={{ width: '250px', minWidth: '250px', background: '#080808', borderRight: '1px solid #181818', display: 'flex', flexDirection: 'column', height: '100%', userSelect: 'none' }}>
        {/* Brand Header */}
        <div style={{ padding: '16px 16px 12px', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <img src={brandLogo} alt="AI Marketing Logo" style={{ width: '24px', height: '24px', objectFit: 'contain' }} />
          <div>
            <div style={{ fontSize: '13px', fontWeight: 700, letterSpacing: '0.4px', color: '#F2F2F2' }}>AI MARKETING</div>
            <div style={{ fontSize: '9.5px', color: '#666666', fontWeight: 500, letterSpacing: '0.3px' }}>DESKTOP APP • 5 PERMANENT AGENTS</div>
          </div>
        </div>

        {/* New Chat Button */}
        <div style={{ padding: '0 12px 14px' }}>
          <button
            onClick={handleCreateNewChat}
            style={{
              width: '100%',
              height: '36px',
              background: '#121212',
              border: '1px solid #202020',
              borderRadius: '8px',
              color: '#F2F2F2',
              fontSize: '13px',
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              cursor: 'pointer',
              transition: 'background 0.15s, border-color 0.15s',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = '#171717'; e.currentTarget.style.borderColor = '#2A2A2A'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = '#121212'; e.currentTarget.style.borderColor = '#202020'; }}
          >
            <IconPlus size={15} />
            <span>New Chat</span>
          </button>
        </div>

        {/* Recent Chats Section */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 8px 6px', color: '#A0A0A0', fontSize: '12px', fontWeight: 600 }}>
            <IconClock size={14} />
            <span>Recent Chats</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            {chatSessions.length === 0 ? (
              <div style={{ padding: '12px 8px', fontSize: '12px', color: '#666666', fontStyle: 'italic' }}>No active conversations</div>
            ) : (
              chatSessions.slice(0, 15).map((s) => {
                const isActive = s.chat_id === activeChatId && activeView === 'chat';
                return (
                  <div
                    key={s.chat_id}
                    onClick={() => { setActiveChatId(s.chat_id); setActiveView('chat'); }}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '7px 8px',
                      borderRadius: '6px',
                      background: isActive ? '#171717' : 'transparent',
                      color: isActive ? '#F2F2F2' : '#A0A0A0',
                      fontSize: '13px',
                      cursor: 'pointer',
                      transition: 'background 0.12s',
                    }}
                    onMouseEnter={(e) => {
                      if (!isActive) e.currentTarget.style.background = '#0F0F0F';
                      const actions = e.currentTarget.querySelector('.chat-actions') as HTMLElement;
                      if (actions) actions.style.opacity = '1';
                    }}
                    onMouseLeave={(e) => {
                      if (!isActive) e.currentTarget.style.background = 'transparent';
                      const actions = e.currentTarget.querySelector('.chat-actions') as HTMLElement;
                      if (actions) actions.style.opacity = '0';
                    }}
                  >
                    {editingChatId === s.chat_id ? (
                      <input
                        type="text"
                        value={editChatTitle}
                        onChange={(e) => setEditChatTitle(e.target.value)}
                        onBlur={() => handleRenameChat(s.chat_id, editChatTitle)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleRenameChat(s.chat_id, editChatTitle);
                          if (e.key === 'Escape') setEditingChatId(null);
                        }}
                        autoFocus
                        style={{ width: '100%', background: '#0D0D0D', border: '1px solid #282828', borderRadius: '4px', color: '#F2F2F2', fontSize: '12px', padding: '2px 6px', outline: 'none' }}
                        onClick={(e) => e.stopPropagation()}
                      />
                    ) : (
                      <>
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '140px' }}>
                          {s.title || 'Untitled Chat'}
                        </span>

                        <div className="chat-actions" style={{ display: 'flex', alignItems: 'center', gap: '3px', opacity: 0, transition: 'opacity 0.15s' }} onClick={(e) => e.stopPropagation()}>
                          <button
                            title="Rename"
                            onClick={() => { setEditingChatId(s.chat_id); setEditChatTitle(s.title); }}
                            style={{ background: 'transparent', border: 'none', color: '#8E8E8E', cursor: 'pointer', padding: '3px', borderRadius: '4px', display: 'flex', alignItems: 'center' }}
                            onMouseEnter={(e) => { e.currentTarget.style.color = '#F2F2F2'; e.currentTarget.style.background = 'rgba(255,255,255,0.06)'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.color = '#8E8E8E'; e.currentTarget.style.background = 'transparent'; }}
                          >
                            <IconEdit size={13} />
                          </button>
                          <button
                            title="Archive"
                            onClick={() => handleArchiveChat(s.chat_id)}
                            style={{ background: 'transparent', border: 'none', color: '#8E8E8E', cursor: 'pointer', padding: '3px', borderRadius: '4px', display: 'flex', alignItems: 'center' }}
                            onMouseEnter={(e) => { e.currentTarget.style.color = '#F2F2F2'; e.currentTarget.style.background = 'rgba(255,255,255,0.06)'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.color = '#8E8E8E'; e.currentTarget.style.background = 'transparent'; }}
                          >
                            <IconArchive size={13} />
                          </button>
                          <button
                            title="Delete"
                            onClick={() => handleDeleteChat(s.chat_id)}
                            style={{ background: 'transparent', border: 'none', color: '#8E8E8E', cursor: 'pointer', padding: '3px', borderRadius: '4px', display: 'flex', alignItems: 'center' }}
                            onMouseEnter={(e) => { e.currentTarget.style.color = '#F2F2F2'; e.currentTarget.style.background = 'rgba(255,255,255,0.06)'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.color = '#8E8E8E'; e.currentTarget.style.background = 'transparent'; }}
                          >
                            <IconTrash size={13} />
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {/* Workspaces & Tools Section */}
          <div style={{ marginTop: '20px', paddingTop: '12px', borderTop: '1px solid #141414' }}>
            <div style={{ padding: '4px 8px 8px', color: '#666666', fontSize: '10px', fontWeight: 700, letterSpacing: '0.5px' }}>
              WORKSPACES & TOOLS
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
              {[
                { id: 'projects', label: `Projects (${projects.length})`, icon: IconFolder },
                { id: 'brands', label: `Brands (${workspaces.length})`, icon: IconBuilding },
                { id: 'dashboard', label: 'Dashboard', icon: IconLayout },
                { id: 'knowledge', label: 'Knowledge', icon: IconBook },
                { id: 'approvals', label: `Approvals (${pendingApprovals.length})`, icon: IconShieldCheck },
                { id: 'connections', label: `Connections (${Object.keys(connectorHealth).length})`, icon: IconPlug },
                { id: 'activity', label: `Receipts & Lineage (${receipts.length})`, icon: IconReceipt },
                { id: 'settings', label: 'AI Model Settings', icon: IconSettings },
              ].map((item) => {
                const isItemActive = activeView === item.id;
                const IconComponent = item.icon;
                return (
                  <div
                    key={item.id}
                    onClick={() => setActiveView(item.id as any)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '9px',
                      padding: '7px 8px',
                      borderRadius: '6px',
                      background: isItemActive ? '#171717' : 'transparent',
                      color: isItemActive ? '#F2F2F2' : '#A0A0A0',
                      fontSize: '13px',
                      cursor: 'pointer',
                      transition: 'background 0.12s',
                    }}
                    onMouseEnter={(e) => { if (!isItemActive) e.currentTarget.style.background = '#0F0F0F'; }}
                    onMouseLeave={(e) => { if (!isItemActive) e.currentTarget.style.background = 'transparent'; }}
                  >
                    <IconComponent size={15} />
                    <span>{item.label}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Bottom Sidebar: Settings & User Profile */}
        <div style={{ borderTop: '1px solid #141414', padding: '10px 8px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <div
            style={{ display: 'flex', alignItems: 'center', gap: '9px', padding: '6px 8px', borderRadius: '6px', color: '#A0A0A0', fontSize: '13px', cursor: 'pointer' }}
            onMouseEnter={(e) => (e.currentTarget.style.background = '#0F0F0F')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
          >
            <IconSettings size={15} />
            <span>Settings</span>
          </div>

          <div
            style={{ display: 'flex', alignItems: 'center', gap: '9px', padding: '6px 8px', borderRadius: '6px', color: '#A0A0A0', cursor: 'pointer' }}
            onMouseEnter={(e) => (e.currentTarget.style.background = '#0F0F0F')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
          >
            <div style={{ width: '22px', height: '22px', borderRadius: '50%', background: '#171717', border: '1px solid #222222', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <IconUser size={13} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontSize: '12px', color: '#F2F2F2', fontWeight: 600, lineHeight: 1.2 }}>User</span>
              <span style={{ fontSize: '10.5px', color: '#666666', lineHeight: 1.2 }}>user@example.com</span>
            </div>
          </div>
        </div>
      </aside>

      {/* ========================================================
          CENTER MAIN VIEW (#050505)
      ======================================================== */}
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', background: '#050505', position: 'relative', overflow: 'hidden' }}>
        {/* Top Header Bar */}
        <header style={{ height: '48px', minHeight: '48px', borderBottom: '1px solid #141414', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 20px', background: '#050505' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontSize: '13.5px', fontWeight: 700, color: '#F2F2F2' }}>
              {activeView === 'chat' ? (activeChat?.title || 'Ad-Hoc Exploration') : activeView.toUpperCase()}
            </span>
            {activeView === 'chat' && (
              <span style={{ background: '#121212', border: '1px solid #202020', borderRadius: '6px', padding: '2px 8px', fontSize: '11px', color: '#888888', fontWeight: 500 }}>
                Zero Brand Required (Session Context Only)
              </span>
            )}
          </div>

          <button
            onClick={() => setShowRightDrawer((prev) => !prev)}
            style={{
              background: 'transparent',
              border: '1px solid #202020',
              borderRadius: '6px',
              padding: '4px 10px',
              color: '#A0A0A0',
              fontSize: '12px',
              fontWeight: 500,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer',
              transition: 'background 0.15s',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = '#121212'; e.currentTarget.style.color = '#F2F2F2'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#A0A0A0'; }}
          >
            <span>{showRightDrawer ? 'Hide Activity' : 'Show Activity'}</span>
            {showRightDrawer ? <IconChevronRight size={13} /> : <IconChevronLeft size={13} />}
          </button>
        </header>

        {/* Scrollable Conversation Content Area */}
        <div ref={scrollContainerRef} style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', position: 'relative' }}>
          {activeView === 'chat' ? (
            !activeChat || activeChat.messages.length === 0 ? (
              /* Central Empty State Hero */
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '40px 20px', textAlign: 'center' }}>
                <img src={brandLogo} alt="AI Marketing Department" style={{ width: '48px', height: '48px', objectFit: 'contain', marginBottom: '14px' }} />
                <h1 style={{ fontSize: '18px', fontWeight: 700, color: '#F2F2F2', margin: '0 0 6px 0' }}>
                  Five-Agent Marketing Department
                </h1>
                <p style={{ fontSize: '13px', color: '#8E8E8E', maxWidth: '520px', lineHeight: 1.5, margin: 0 }}>
                  Type any objective, attach PDFs/CSVs, or paste a URL. The Five-Agent Brain will execute immediately using session context. No brand setup required.
                </p>
              </div>
            ) : (
              /* Message Thread List */
              <div style={{ maxWidth: '780px', width: '100%', margin: '0 auto', padding: '24px 20px 140px' }}>
                {activeChat.messages.map((m) => {
                  const isUser = m.role === 'user';
                  const isError = m.status === 'ERROR' || m.content.startsWith('⚠️');
                  const isEditingThis = editingMsgId === m.message_id;

                  return (
                    <div
                      key={m.message_id}
                      style={{
                        marginBottom: '26px',
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: isUser ? 'flex-end' : 'flex-start',
                      }}
                    >
                      {/* Sender label / icon */}
                      {!isUser && (
                        <div style={{ fontSize: '11px', color: '#777777', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600 }}>
                          <img src={brandLogo} alt="AI" style={{ width: '13px', height: '13px', objectFit: 'contain' }} />
                          <span>{m.sender_name || 'AI Marketing Department'}</span>
                        </div>
                      )}

                      {/* Message Body or Inline Editor */}
                      {isUser && isEditingThis ? (
                        <div style={{ width: '100%', maxWidth: '780px', background: '#0D0D0D', border: '1px solid #282828', borderRadius: '12px', padding: '12px 14px' }}>
                          <textarea
                            ref={editMsgTextareaRef}
                            value={editingMsgContent}
                            onChange={(e) => setEditingMsgContent(e.target.value)}
                            style={{ width: '100%', background: 'transparent', border: 'none', outline: 'none', color: '#F2F2F2', fontSize: '14px', lineHeight: '1.6', resize: 'none', minHeight: '60px', fontFamily: 'inherit' }}
                          />
                          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '8px', paddingTop: '6px', borderTop: '1px solid #1C1C1C' }}>
                            <button
                              onClick={handleCancelEditMessage}
                              style={{ background: 'transparent', border: '1px solid #282828', borderRadius: '6px', color: '#A0A0A0', fontSize: '12px', padding: '5px 12px', cursor: 'pointer' }}
                            >
                              Cancel
                            </button>
                            <button
                              onClick={() => handleSendEditedMessage(m.message_id)}
                              style={{ background: '#ECECEC', border: 'none', borderRadius: '6px', color: '#050505', fontSize: '12px', fontWeight: 600, padding: '5px 14px', cursor: 'pointer' }}
                            >
                              Send
                            </button>
                          </div>
                        </div>
                      ) : isError ? (
                        /* Compact Error State with Retry and Copy Error (Preserves partial streamed text if present) */
                        <div style={{ width: '100%', background: '#0E0E0E', border: '1px solid #2E2020', borderRadius: '10px', padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                          {m.content && !m.content.startsWith('⚠️') && !m.content.startsWith('Lỗi') ? (
                            <div style={{ marginBottom: '6px' }}>
                              <MarkdownView content={m.content} />
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#EF4444', fontSize: '12px', marginTop: '8px', fontWeight: 500 }}>
                                <IconAlertCircle size={13} />
                                <span>Luồng phản hồi bị gián đoạn (STREAM_INTERRUPTED).</span>
                              </div>
                            </div>
                          ) : (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#EF4444', fontSize: '13px', fontWeight: 500 }}>
                              <IconAlertCircle size={15} />
                              <span>{m.content || 'Đã xảy ra lỗi trong quá trình xử lý.'}</span>
                            </div>
                          )}
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '2px' }}>
                            <button
                              onClick={handleRetry}
                              style={{ background: '#1C1C1C', border: '1px solid #2C2C2C', borderRadius: '6px', color: '#F2F2F2', fontSize: '12px', padding: '4px 10px', display: 'flex', alignItems: 'center', gap: '5px', cursor: 'pointer' }}
                              onMouseEnter={(e) => (e.currentTarget.style.background = '#252525')}
                              onMouseLeave={(e) => (e.currentTarget.style.background = '#1C1C1C')}
                            >
                              <IconRotateCw size={12} />
                              <span>Thử lại</span>
                            </button>
                            <button
                              onClick={() => handleCopyText(m.content, m.message_id)}
                              style={{ background: 'transparent', border: '1px solid #222222', borderRadius: '6px', color: '#888888', fontSize: '12px', padding: '4px 10px', display: 'flex', alignItems: 'center', gap: '5px', cursor: 'pointer' }}
                              onMouseEnter={(e) => (e.currentTarget.style.color = '#F2F2F2')}
                              onMouseLeave={(e) => (e.currentTarget.style.color = '#888888')}
                            >
                              {copiedMsgId === m.message_id ? <IconCheck size={12} /> : <IconCopy size={12} />}
                              <span>{copiedMsgId === m.message_id ? 'Đã sao chép' : 'Sao chép'}</span>
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div
                          style={{
                            maxWidth: isUser ? '80%' : '100%',
                            width: isUser ? 'auto' : '100%',
                            background: isUser ? '#16181D' : 'transparent',
                            border: isUser ? '1px solid #22252B' : 'none',
                            borderRadius: isUser ? '14px 14px 2px 14px' : '0',
                            padding: isUser ? '10px 16px' : '0',
                          }}
                        >
                          {isUser ? (
                            <div style={{ color: '#F2F2F2', fontSize: '14px', lineHeight: '1.6', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                              {m.content}
                            </div>
                          ) : m.status === 'STREAMING' && !m.content ? (
                            <div style={{ color: '#8E8E8E', fontSize: '13px', fontStyle: 'italic' }}>
                              Đang nhận phản hồi...
                            </div>
                          ) : (
                            <MarkdownView content={m.content} />
                          )}

                          {/* Attachments inside user message */}
                          {m.attachments && m.attachments.length > 0 && (
                            <div style={{ marginTop: '8px', paddingTop: '6px', borderTop: '1px solid #22252B', display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                              {m.attachments.map((att, i) => (
                                <span
                                  key={i}
                                  style={{ background: '#101216', border: '1px solid #20242D', color: '#A0A0A0', padding: '2px 7px', borderRadius: '4px', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}
                                >
                                  <IconPaperclip size={11} />
                                  <span>{att.filename_or_url} ({att.attachment_type})</span>
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {/* Message Action Bar (Copy, Edit, Regenerate) */}
                      {!isEditingThis && !isError && (
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '4px',
                            marginTop: '6px',
                            padding: '0 2px',
                            color: '#777777',
                            fontSize: '11px',
                          }}
                        >
                          <button
                            title="Copy message"
                            onClick={() => handleCopyText(m.content, m.message_id)}
                            style={{
                              background: 'transparent',
                              border: 'none',
                              color: copiedMsgId === m.message_id ? '#4ADE80' : '#777777',
                              cursor: 'pointer',
                              padding: '3px 6px',
                              borderRadius: '4px',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '4px',
                              fontSize: '11px',
                              transition: 'color 0.15s, background 0.15s',
                            }}
                            onMouseEnter={(e) => { if (copiedMsgId !== m.message_id) { e.currentTarget.style.color = '#F2F2F2'; e.currentTarget.style.background = 'rgba(255,255,255,0.06)'; } }}
                            onMouseLeave={(e) => { if (copiedMsgId !== m.message_id) { e.currentTarget.style.color = '#777777'; e.currentTarget.style.background = 'transparent'; } }}
                          >
                            {copiedMsgId === m.message_id ? <IconCheck size={12} /> : <IconCopy size={12} />}
                            <span>{copiedMsgId === m.message_id ? 'Copied' : 'Copy'}</span>
                          </button>

                          {isUser && (
                            <button
                              title="Edit message"
                              onClick={() => handleStartEditMessage(m)}
                              style={{
                                background: 'transparent',
                                border: 'none',
                                color: '#777777',
                                cursor: 'pointer',
                                padding: '3px 6px',
                                borderRadius: '4px',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px',
                                fontSize: '11px',
                                transition: 'color 0.15s, background 0.15s',
                              }}
                              onMouseEnter={(e) => { e.currentTarget.style.color = '#F2F2F2'; e.currentTarget.style.background = 'rgba(255,255,255,0.06)'; }}
                              onMouseLeave={(e) => { e.currentTarget.style.color = '#777777'; e.currentTarget.style.background = 'transparent'; }}
                            >
                              <IconEdit size={12} />
                              <span>Edit</span>
                            </button>
                          )}

                          {!isUser && (
                            <button
                              title="Regenerate response"
                              onClick={() => handleRegenerate(m.message_id)}
                              style={{
                                background: 'transparent',
                                border: 'none',
                                color: '#777777',
                                cursor: 'pointer',
                                padding: '3px 6px',
                                borderRadius: '4px',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px',
                                fontSize: '11px',
                                transition: 'color 0.15s, background 0.15s',
                              }}
                              onMouseEnter={(e) => { e.currentTarget.style.color = '#F2F2F2'; e.currentTarget.style.background = 'rgba(255,255,255,0.06)'; }}
                              onMouseLeave={(e) => { e.currentTarget.style.color = '#777777'; e.currentTarget.style.background = 'transparent'; }}
                            >
                              <IconRotateCw size={12} />
                              <span>Regenerate</span>
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}

                {/* Processing Indicator */}
                {isProcessing && (
                  <div style={{ background: '#0D0D0D', border: '1px solid #181818', borderRadius: '12px', padding: '16px 20px', marginBottom: '20px' }}>
                    <div style={{ color: '#F2F2F2', fontWeight: 700, fontSize: '13px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <img src={brandLogo} alt="AI" style={{ width: '15px', height: '15px', objectFit: 'contain' }} />
                      <span>AI Marketing Department is working...</span>
                    </div>
                    {agentProgress && <div style={{ color: '#888888', fontSize: '12px', marginTop: '6px' }}>{agentProgress}</div>}
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>
            )
          ) : activeView === 'settings' ? (
            /* Dedicated Model & Provider Settings View */
            <ModelSettingsView />
          ) : (
            /* Alternate Workspace Views (Brands, Projects, Dashboard, Knowledge, etc.) */
            <div style={{ padding: '30px 40px', maxWidth: '900px', margin: '0 auto', width: '100%' }}>
              <h2 style={{ fontSize: '18px', fontWeight: 700, marginBottom: '16px', color: '#F2F2F2' }}>
                {activeView.toUpperCase()} OVERVIEW
              </h2>
              <div style={{ background: '#0D0D0D', border: '1px solid #181818', borderRadius: '10px', padding: '20px', color: '#A0A0A0', fontSize: '13px' }}>
                Workspace view for <strong>{activeView}</strong> is active. Use the Left Sidebar to switch back to Chat.
              </div>
            </div>
          )}
        </div>

        {/* ========================================================
            FIXED CHAT COMPOSER (#0D0D0D / #121212)
        ======================================================== */}
        {activeView === 'chat' && (
          <div style={{ position: 'absolute', bottom: '0', left: '0', right: '0', background: 'linear-gradient(to top, #050505 80%, rgba(5,5,5,0) 100%)', padding: '10px 20px 14px', pointerEvents: 'none' }}>
            <div style={{ maxWidth: '780px', margin: '0 auto', pointerEvents: 'auto', position: 'relative' }}>
              {/* Attachment Preview Chips */}
              {attachments.length > 0 && (
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '8px' }}>
                  {attachments.map((att, idx) => (
                    <div
                      key={idx}
                      style={{ background: '#121212', border: '1px solid #202020', borderRadius: '6px', padding: '3px 8px', fontSize: '11px', color: '#ECECEC', display: 'flex', alignItems: 'center', gap: '6px' }}
                    >
                      <IconPaperclip size={11} />
                      <span>{att.filename_or_url}</span>
                      <button
                        onClick={() => setAttachments((prev) => prev.filter((_, i) => i !== idx))}
                        style={{ background: 'transparent', border: 'none', color: '#888888', cursor: 'pointer', padding: '0 2px', display: 'flex', alignItems: 'center' }}
                      >
                        <IconClose size={11} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* Floating Attachment Popover Menu */}
              {showAttachmentMenu && (
                <div
                  ref={attachmentMenuRef}
                  style={{
                    position: 'absolute',
                    bottom: '72px',
                    left: '12px',
                    background: '#0D0D0D',
                    border: '1px solid #202020',
                    borderRadius: '10px',
                    boxShadow: '0 10px 30px rgba(0,0,0,0.8)',
                    padding: '6px',
                    width: '220px',
                    zIndex: 100,
                  }}
                >
                  <button
                    onClick={() => { computerFileInputRef.current?.click(); setShowAttachmentMenu(false); }}
                    style={{ width: '100%', display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 10px', background: 'transparent', border: 'none', borderRadius: '6px', color: '#F2F2F2', fontSize: '13px', textAlign: 'left', cursor: 'pointer' }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = '#171717')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <IconMonitor size={15} />
                    <span>Upload from computer</span>
                  </button>

                  <button
                    onClick={() => { fileInputRef.current?.click(); setShowAttachmentMenu(false); }}
                    style={{ width: '100%', display: 'flex', flexDirection: 'column', padding: '8px 10px', background: 'transparent', border: 'none', borderRadius: '6px', color: '#F2F2F2', textAlign: 'left', cursor: 'pointer' }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = '#171717')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '13px' }}>
                      <IconFileText size={15} />
                      <span>Upload file</span>
                    </div>
                    <span style={{ fontSize: '10px', color: '#666666', marginLeft: '25px', marginTop: '2px' }}>
                      PDF, CSV, XLSX, DOCX, PPTX, TXT
                    </span>
                  </button>

                  <button
                    onClick={() => { setShowPasteModal(true); setShowAttachmentMenu(false); }}
                    style={{ width: '100%', display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 10px', background: 'transparent', border: 'none', borderRadius: '6px', color: '#F2F2F2', fontSize: '13px', textAlign: 'left', cursor: 'pointer' }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = '#171717')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <IconClipboard size={15} />
                    <span>Paste text</span>
                  </button>

                  <button
                    onClick={() => { setUrlModalOpen(true); setShowAttachmentMenu(false); }}
                    style={{ width: '100%', display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 10px', background: 'transparent', border: 'none', borderRadius: '6px', color: '#F2F2F2', fontSize: '13px', textAlign: 'left', cursor: 'pointer' }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = '#171717')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <IconLink size={15} />
                    <span>Add URL</span>
                  </button>
                </div>
              )}

              {/* Backend Health Status Banner */}
              {backendState === 'STARTING_BACKEND' && (
                <div style={{ marginBottom: '8px', padding: '8px 12px', background: '#111317', border: '1px solid #1D222A', borderRadius: '8px', color: '#9CA3AF', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <IconRotateCw size={13} style={{ animation: 'spin 1s linear infinite' }} />
                  <span>Đang kết nối với dịch vụ backend cục bộ...</span>
                </div>
              )}
              {backendState === 'BACKEND_FAILED' && (
                <div style={{ marginBottom: '8px', padding: '10px 14px', background: '#1A0E0E', border: '1px solid #3D1C1C', borderRadius: '8px', color: '#EF4444', fontSize: '12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <IconAlertCircle size={14} />
                    <span>{backendErrorDetail || 'Không thể kết nối với dịch vụ backend cục bộ (BACKEND_UNAVAILABLE).'}</span>
                  </div>
                  <button
                    onClick={fetchCoreData}
                    style={{ background: '#2B1414', border: '1px solid #522020', color: '#FCA5A5', borderRadius: '6px', padding: '4px 10px', fontSize: '11px', fontWeight: 600, cursor: 'pointer', flexShrink: 0 }}
                  >
                    Thử lại
                  </button>
                </div>
              )}

              {/* Composer Box */}
              <div
                style={{
                  background: '#0D0D0D',
                  border: '1px solid #202020',
                  borderRadius: '14px',
                  padding: '12px 14px 8px',
                  display: 'flex',
                  flexDirection: 'column',
                  transition: 'border-color 0.15s',
                }}
              >
                <textarea
                  ref={textareaRef}
                  value={chatInput}
                  onChange={handleTextareaChange}
                  onKeyDown={handleKeyDown}
                  placeholder={backendState === 'STARTING_BACKEND' ? 'Đang kết nối backend...' : 'Message Five-Agent Marketing Department...'}
                  disabled={backendState !== 'BACKEND_READY'}
                  rows={1}
                  style={{
                    width: '100%',
                    background: 'transparent',
                    border: 'none',
                    outline: 'none',
                    color: '#F2F2F2',
                    fontSize: '14px',
                    lineHeight: '1.5',
                    resize: 'none',
                    minHeight: '42px',
                    maxHeight: '200px',
                    fontFamily: 'inherit',
                  }}
                />

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '6px', paddingTop: '4px' }}>
                  {/* Left: + Attachment Button */}
                  <button
                    onClick={() => setShowAttachmentMenu((prev) => !prev)}
                    disabled={backendState !== 'BACKEND_READY'}
                    style={{
                      width: '28px',
                      height: '28px',
                      borderRadius: '50%',
                      background: '#16181D',
                      border: '1px solid #22252B',
                      color: '#A0A0A0',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      cursor: backendState === 'BACKEND_READY' ? 'pointer' : 'default',
                      opacity: backendState === 'BACKEND_READY' ? 1 : 0.5,
                      transition: 'background 0.15s, color 0.15s',
                    }}
                    onMouseEnter={(e) => { if (backendState === 'BACKEND_READY') { e.currentTarget.style.background = '#202020'; e.currentTarget.style.color = '#F2F2F2'; } }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = '#16181D'; e.currentTarget.style.color = '#A0A0A0'; }}
                  >
                    <IconPlus size={15} />
                  </button>

                  {/* Right: Send Button */}
                  <button
                    onClick={handleSendMessage}
                    disabled={backendState !== 'BACKEND_READY' || (!chatInput.trim() && attachments.length === 0)}
                    style={{
                      width: '28px',
                      height: '28px',
                      borderRadius: '50%',
                      background: backendState === 'BACKEND_READY' && (chatInput.trim() || attachments.length > 0) ? '#ECECEC' : '#222222',
                      border: 'none',
                      color: backendState === 'BACKEND_READY' && (chatInput.trim() || attachments.length > 0) ? '#050505' : '#666666',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      cursor: backendState === 'BACKEND_READY' && (chatInput.trim() || attachments.length > 0) ? 'pointer' : 'default',
                      transition: 'background 0.15s, color 0.15s',
                    }}
                  >
                    <IconSend size={15} />
                  </button>
                </div>
              </div>

              <div style={{ textAlign: 'center', color: '#666666', fontSize: '11px', marginTop: '6px' }}>
                Five-Agent Brain may make mistakes. Please verify important information.
              </div>
            </div>
          </div>
        )}
      </main>

      {/* ========================================================
          RIGHT FIVE-AGENT ACTIVITY PANEL (#080808)
      ======================================================== */}
      {showRightDrawer && (
        <aside style={{ width: '270px', minWidth: '270px', background: '#080808', borderLeft: '1px solid #181818', display: 'flex', flexDirection: 'column', height: '100%', padding: '16px', overflowY: 'auto' }}>
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
            <img src={brandLogo} alt="Five-Agent Logo" style={{ width: '14px', height: '14px', objectFit: 'contain' }} />
            <span style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '0.5px', color: '#A0A0A0', textTransform: 'uppercase' }}>
              FIVE-AGENT ACTIVITY
            </span>
          </div>

          {/* 5 Permanent Agent Cards */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '24px' }}>
            {[
              { id: 'cmo', name: 'CMO', desc: agentStates.cmo.detail },
              { id: 'intelligence', name: 'Intelligence', desc: agentStates.intelligence.detail },
              { id: 'strategist', name: 'Strategist', desc: agentStates.strategist.detail },
              { id: 'creative', name: 'Creative', desc: agentStates.creative.detail },
              { id: 'performance', name: 'Performance', desc: agentStates.performance.detail },
            ].map((agent) => {
              const state = agentStates[agent.id]?.status || 'READY';
              const isWorking = state === 'WORKING';
              return (
                <div
                  key={agent.id}
                  style={{
                    background: '#0D0D0D',
                    border: '1px solid #181818',
                    borderRadius: '8px',
                    padding: '10px 14px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '4px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontSize: '13px', fontWeight: 600, color: '#F2F2F2' }}>{agent.name}</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                      <span
                        style={{
                          width: '6px',
                          height: '6px',
                          borderRadius: '50%',
                          background: isWorking ? '#F59E0B' : '#4ADE80',
                        }}
                      />
                      <span style={{ fontSize: '11px', color: isWorking ? '#F59E0B' : '#A0A0A0', fontWeight: 500 }}>
                        {isWorking ? 'WORKING' : 'READY'}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* 6 Workflow Stages (Active / Truthful Execution) */}
          {workflowStages.some((s) => s.status !== 'PENDING') && (
            <div style={{ marginBottom: '20px' }}>
              <div style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.5px', color: '#666666', textTransform: 'uppercase', marginBottom: '8px' }}>
                WORKFLOW STAGES
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {workflowStages.map((st) => {
                  const isDone = st.status === 'COMPLETED';
                  const isActive = st.status === 'ACTIVE';
                  const isFailed = st.status === 'FAILED';
                  return (
                    <div
                      key={st.stage}
                      style={{
                        background: '#0D0D0D',
                        border: `1px solid ${isFailed ? '#451A1A' : isActive ? '#282828' : '#141414'}`,
                        borderRadius: '6px',
                        padding: '6px 10px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                      }}
                    >
                      <span style={{ fontSize: '11.5px', color: isFailed ? '#EF4444' : isDone ? '#4ADE80' : isActive ? '#F59E0B' : '#777777', fontWeight: 500 }}>
                        {st.label}
                      </span>
                      <span style={{ fontSize: '10px', color: isFailed ? '#EF4444' : isDone ? '#4ADE80' : isActive ? '#F59E0B' : '#555555', fontWeight: 600 }}>
                        {st.status}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Session Attachments Section */}
          <div>
            <div style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.5px', color: '#666666', textTransform: 'uppercase', marginBottom: '8px' }}>
              SESSION ATTACHMENTS
            </div>
            <div style={{ fontSize: '12px', color: '#666666', fontStyle: 'italic' }}>
              {attachments.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {attachments.map((a, i) => (
                    <div key={i} style={{ color: '#A0A0A0', fontStyle: 'normal', fontSize: '12px' }}>
                      📎 {a.filename_or_url}
                    </div>
                  ))}
                </div>
              ) : (
                'No active attachments.'
              )}
            </div>
          </div>
        </aside>
      )}

      {/* ========================================================
          MODALS: PASTE TEXT & ADD URL
      ======================================================== */}
      {showPasteModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div style={{ background: '#0D0D0D', border: '1px solid #202020', borderRadius: '12px', padding: '20px', width: '440px', maxWidth: '90%' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#F2F2F2', margin: '0 0 12px 0' }}>Paste Text Attachment</h3>
            <input
              type="text"
              placeholder="Note Title..."
              value={pasteModalTitle}
              onChange={(e) => setPasteModalTitle(e.target.value)}
              style={{ width: '100%', background: '#16181D', border: '1px solid #22252B', borderRadius: '6px', color: '#F2F2F2', fontSize: '13px', padding: '8px 12px', marginBottom: '10px', outline: 'none' }}
            />
            <textarea
              placeholder="Paste content here..."
              rows={6}
              value={pasteModalContent}
              onChange={(e) => setPasteModalContent(e.target.value)}
              style={{ width: '100%', background: '#16181D', border: '1px solid #22252B', borderRadius: '6px', color: '#F2F2F2', fontSize: '13px', padding: '8px 12px', marginBottom: '16px', outline: 'none', resize: 'vertical' }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button
                onClick={() => setShowPasteModal(false)}
                style={{ background: 'transparent', border: '1px solid #22252B', borderRadius: '6px', color: '#A0A0A0', fontSize: '12px', padding: '6px 12px', cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                onClick={handleSavePastedText}
                style={{ background: '#ECECEC', border: 'none', borderRadius: '6px', color: '#050505', fontSize: '12px', fontWeight: 600, padding: '6px 14px', cursor: 'pointer' }}
              >
                Attach Note
              </button>
            </div>
          </div>
        </div>
      )}

      {urlModalOpen && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div style={{ background: '#0D0D0D', border: '1px solid #202020', borderRadius: '12px', padding: '20px', width: '440px', maxWidth: '90%' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#F2F2F2', margin: '0 0 12px 0' }}>Add Web URL</h3>
            <input
              type="url"
              placeholder="https://example.com/article..."
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              style={{ width: '100%', background: '#16181D', border: '1px solid #22252B', borderRadius: '6px', color: '#F2F2F2', fontSize: '13px', padding: '8px 12px', marginBottom: '16px', outline: 'none' }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button
                onClick={() => setUrlModalOpen(false)}
                style={{ background: 'transparent', border: '1px solid #22252B', borderRadius: '6px', color: '#A0A0A0', fontSize: '12px', padding: '6px 12px', cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                onClick={handleSaveUrlAttachment}
                style={{ background: '#ECECEC', border: 'none', borderRadius: '6px', color: '#050505', fontSize: '12px', fontWeight: 600, padding: '6px 14px', cursor: 'pointer' }}
              >
                Attach URL
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
