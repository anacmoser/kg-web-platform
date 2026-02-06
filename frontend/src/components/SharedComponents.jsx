import React from 'react';

export const ProgressBar = ({ progress, status }) => {
    const percentage = Math.round(progress * 100);

    const getStatusColor = () => {
        switch (status) {
            case 'completed': return 'bg-green-500';
            case 'failed': return 'bg-red-500';
            case 'processing': return 'bg-seade-blue-primary';
            default: return 'bg-gray-400';
        }
    };

    return (
        <div className="w-full">
            <div className="flex justify-between mb-1">
                <span className="text-sm font-medium text-seade-gray-dark">
                    {status === 'completed' ? 'Complete' : `${percentage}%`}
                </span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2.5">
                <div
                    className={`h-2.5 rounded-full transition-all duration-300 ${getStatusColor()}`}
                    style={{ width: `${percentage}%` }}
                />
            </div>
        </div>
    );
};

export const LoadingSpinner = ({ size = 'md' }) => {
    const sizeClasses = {
        sm: 'w-4 h-4',
        md: 'w-8 h-8',
        lg: 'w-12 h-12'
    };

    return (
        <div className="flex justify-center items-center">
            <div className={`${sizeClasses[size]} border-4 border-seade-gray-medium border-t-seade-blue-primary rounded-full animate-spin`} />
        </div>
    );
};

export const ErrorAlert = ({ message, onDismiss }) => {
    if (!message) return null;

    return (
        <div className="bg-red-50 border-l-4 border-red-500 p-4 mb-4">
            <div className="flex">
                <div className="flex-shrink-0">
                    <svg className="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                    </svg>
                </div>
                <div className="ml-3 flex-1">
                    <p className="text-sm text-red-700">{message}</p>
                </div>
                {onDismiss && (
                    <button onClick={onDismiss} className="ml-auto">
                        <span className="text-red-500 hover:text-red-700">×</span>
                    </button>
                )}
            </div>
        </div>
    );
};

export const JobStatusBadge = ({ status }) => {
    const statusConfig = {
        queued: { bg: 'bg-gray-100', text: 'text-gray-800', label: 'Queued' },
        processing: { bg: 'bg-blue-100', text: 'text-blue-800', label: 'Processing' },
        completed: { bg: 'bg-green-100', text: 'text-green-800', label: 'Completed' },
        failed: { bg: 'bg-red-100', text: 'text-red-800', label: 'Failed' }
    };

    const config = statusConfig[status] || statusConfig.queued;

    return (
        <span className={`px-3 py-1 rounded-full text-xs font-semibold ${config.bg} ${config.text}`}>
            {config.label}
        </span>
    );
};

export const StatCard = ({ title, value, icon }) => {
    return (
        <div className="bg-white rounded-lg shadow p-6 border-t-4 border-seade-blue-primary">
            <div className="flex items-center justify-between">
                <div>
                    <p className="text-sm text-seade-gray-dark mb-1">{title}</p>
                    <p className="text-3xl font-bold text-seade-blue-dark">{value}</p>
                </div>
                {icon && <div className="text-seade-blue-light text-4xl">{icon}</div>}
            </div>
        </div>
    );
};
