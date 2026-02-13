import React from 'react';

export const ProgressBar = ({ progress, status }) => {
    const percentage = Math.round(progress * 100);

    const getStatusColor = () => {
        switch (status) {
            case 'completed': return 'bg-emerald-500';
            case 'failed': return 'bg-rose-500';
            case 'processing': return 'bg-brand-primary';
            default: return 'bg-slate-300';
        }
    };

    return (
        <div className="w-full">
            <div className="flex justify-between mb-2 items-center">
                <span className="text-xs font-bold uppercase tracking-widest text-brand-muted">
                    {status === 'completed' ? 'Concluído' : status === 'failed' ? 'Falha' : 'Progresso'}
                </span>
                <span className="text-sm font-mono font-bold text-brand-surface">
                    {percentage}%
                </span>
            </div>
            <div className="w-full bg-slate-100 rounded-full h-3 p-0.5 overflow-hidden">
                <div
                    className={`h-full rounded-full transition-all duration-700 ease-out relative ${getStatusColor()}`}
                    style={{ width: `${percentage}%` }}
                >
                    <div className="absolute inset-0 bg-white/20 animate-pulse"></div>
                </div>
            </div>
        </div>
    );
};

export const LoadingSpinner = ({ size = 'md' }) => {
    const sizeClasses = {
        sm: 'w-5 h-5 border-2',
        md: 'w-10 h-10 border-3',
        lg: 'w-16 h-16 border-4'
    };

    return (
        <div className="flex justify-center items-center">
            <div className={`${sizeClasses[size]} border-slate-200 border-t-brand-primary rounded-full animate-spin`} />
        </div>
    );
};

export const ErrorAlert = ({ message, onDismiss }) => {
    if (!message) return null;

    return (
        <div className="bg-rose-50 border border-rose-100 rounded-2xl p-5 mb-6 animate-in fade-in zoom-in duration-300">
            <div className="flex items-start">
                <div className="flex-shrink-0 bg-rose-100 p-2 rounded-xl">
                    <svg className="h-5 w-5 text-rose-600" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                    </svg>
                </div>
                <div className="ml-4 flex-1">
                    <h4 className="text-sm font-bold text-rose-900 mb-1">Ops! Algo deu errado</h4>
                    <p className="text-sm text-rose-700 leading-relaxed">{message}</p>
                </div>
                {onDismiss && (
                    <button onClick={onDismiss} className="ml-auto text-rose-400 hover:text-rose-600 p-1">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                    </button>
                )}
            </div>
        </div>
    );
};

export const JobStatusBadge = ({ status }) => {
    const statusConfig = {
        queued: { bg: 'bg-slate-100', text: 'text-slate-600', label: 'Na Fila' },
        processing: { bg: 'bg-brand-light/30', text: 'text-brand-secondary', label: 'Processando' },
        completed: { bg: 'bg-emerald-100', text: 'text-emerald-700', label: 'Concluído' },
        failed: { bg: 'bg-rose-100', text: 'text-rose-700', label: 'Falhou' }
    };

    const config = statusConfig[status] || statusConfig.queued;

    return (
        <span className={`px-4 py-1.5 rounded-full text-[10px] font-bold uppercase tracking-widest ${config.bg} ${config.text} border border-black/5`}>
            {config.label}
        </span>
    );
};

export const StatCard = ({ title, value, icon }) => {
    return (
        <div className="bg-white rounded-2xl shadow-premium p-6 border-b-4 border-brand-primary hover:translate-y-[-2px] transition-all">
            <div className="flex items-center justify-between">
                <div>
                    <p className="text-xs font-bold text-brand-muted uppercase tracking-widest mb-2">{title}</p>
                    <p className="text-3xl font-display font-extrabold text-brand-surface">{value}</p>
                </div>
                {icon && <div className="p-3 bg-indigo-50 rounded-xl text-3xl">{icon}</div>}
            </div>
        </div>
    );
};
