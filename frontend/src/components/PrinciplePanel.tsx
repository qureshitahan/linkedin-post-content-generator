import { useRef, useState } from 'react';
import { api, friendlyApiError } from '../api/client';
import type { Principle } from '../types';

interface Props {
  principles: Principle[];
  selectedId: number | null;
  onChange: () => void;
}

export default function PrinciplePanel({ principles, selectedId, onChange }: Props) {
  const [expanded, setExpanded] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadTargetId, setUploadTargetId] = useState<number | null>(null);
  const [uploadProgress, setUploadProgress] = useState<{ principleId: number; done: number; total: number } | null>(null);

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    setError(null);
    try {
      await api.createPrinciple(name);
      setNewName('');
      setCreating(false);
      onChange();
    } catch (err) {
      setError(friendlyApiError(err instanceof Error ? err.message : 'Failed to create principle'));
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('Delete this principle and all its documents?')) return;
    setError(null);
    setBusyId(id);
    try {
      await api.deletePrinciple(id);
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete principle');
    } finally {
      setBusyId(null);
    }
  };

  const handleDeleteDocument = async (principleId: number, documentId: number) => {
    if (!window.confirm('Delete this document?')) return;
    setError(null);
    try {
      await api.deletePrincipleDocument(principleId, documentId);
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete document');
    }
  };

  const handleUploadClick = (principleId: number) => {
    setUploadTargetId(principleId);
    fileInputRef.current?.click();
  };

  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    const principleId = uploadTargetId;
    e.target.value = '';
    setUploadTargetId(null);
    if (files.length === 0 || !principleId) return;

    setError(null);
    setBusyId(principleId);
    setUploadProgress({ principleId, done: 0, total: files.length });

    const failures: string[] = [];
    try {
      for (let i = 0; i < files.length; i++) {
        setUploadProgress({ principleId, done: i, total: files.length });
        try {
          await api.uploadPrincipleDocument(principleId, files[i]);
        } catch (err) {
          const msg = err instanceof Error ? err.message : 'Upload failed';
          failures.push(`${files[i].name}: ${msg}`);
        }
      }
      onChange();
      if (failures.length > 0) {
        const succeeded = files.length - failures.length;
        setError(
          succeeded > 0
            ? `Uploaded ${succeeded} of ${files.length}. Failed: ${failures.join('; ')}`
            : failures.join('; '),
        );
      }
    } finally {
      setBusyId(null);
      setUploadProgress(null);
    }
  };

  return (
    <div className="card">
      <div className="mb-3 flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-2 text-left font-semibold text-slate-900"
        >
          <span className="text-slate-400">{expanded ? '▾' : '▸'}</span>
          Manage principles
        </button>
        <button
          type="button"
          onClick={() => setCreating((v) => !v)}
          className="text-xs font-medium text-brand-600 hover:text-brand-700"
        >
          {creating ? 'Cancel' : '+ New'}
        </button>
      </div>

      <p className="mb-3 text-xs text-slate-500">
        Create profiles and upload background files here. Select who you&apos;re writing as in{' '}
        <span className="font-medium text-slate-700">Content Objective</span> on the left.
      </p>

      {error && (
        <p className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </p>
      )}

      {creating && (
        <div className="mb-3 flex gap-2">
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="e.g. Taha"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
          />
          <button type="button" onClick={handleCreate} className="btn-primary px-3 py-2 text-sm">
            Create
          </button>
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".txt,.md,.pdf,.csv,.docx,.png,.jpg,.jpeg,.webp,.gif,.bmp,.tif,.tiff,.heic,.heif"
        className="hidden"
        onChange={handleFileSelected}
      />

      {expanded && (
        <div className="space-y-2">
          {principles.length === 0 ? (
            <p className="text-sm text-slate-400">No principles yet. Create one to get started.</p>
          ) : (
            principles.map((principle) => {
              const isActive = principle.id === selectedId;
              const isBusy = busyId === principle.id;
              const uploading =
                uploadProgress?.principleId === principle.id ? uploadProgress : null;
              const indexedChars = principle.documents.reduce(
                (sum, d) => sum + (d.char_count || 0),
                0,
              );

              return (
                <div
                  key={principle.id}
                  className={`rounded-lg border p-3 ${
                    isActive ? 'border-brand-300 bg-brand-50/30' : 'border-slate-200'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium text-slate-800">{principle.name}</p>
                        {isActive && (
                          <span className="rounded-full bg-brand-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-700">
                            Selected
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {principle.documents.length === 0
                          ? 'No files — add resume & achievements'
                          : `${principle.documents.length} indexed · ${indexedChars.toLocaleString()} chars`}
                      </p>
                    </div>
                    <div className="flex shrink-0 gap-1">
                      <button
                        type="button"
                        onClick={() => handleUploadClick(principle.id)}
                        disabled={isBusy}
                        className="rounded px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
                      >
                        {uploading
                          ? `${uploading.done + 1}/${uploading.total}…`
                          : isBusy
                            ? '…'
                            : 'Add files'}
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(principle.id)}
                        disabled={isBusy}
                        className="rounded px-2 py-1 text-xs text-red-500 hover:bg-red-50 disabled:opacity-50"
                      >
                        Delete
                      </button>
                    </div>
                  </div>

                  {principle.documents.length > 0 && (
                    <ul className="mt-2 space-y-1 border-t border-slate-200/80 pt-2">
                      {principle.documents.map((doc) => (
                        <li
                          key={doc.id}
                          className="flex items-center justify-between gap-2 text-xs text-slate-600"
                        >
                          <span className="truncate" title={doc.filename}>
                            <span className="text-green-600" title="Indexed">●</span>{' '}
                            {doc.filename}
                          </span>
                          <button
                            type="button"
                            onClick={() => handleDeleteDocument(principle.id, doc.id)}
                            className="shrink-0 text-red-500 hover:text-red-700"
                          >
                            Remove
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
