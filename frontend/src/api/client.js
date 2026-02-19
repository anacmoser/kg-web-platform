// API client for backend communication
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:5000/api/v1';

class APIClient {
    async uploadDocument(file, onProgress) {
        const formData = new FormData();
        formData.append('file', file);

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000); // 30s timeout

        try {
            const response = await fetch(`${API_BASE_URL}/documents/upload`, {
                method: 'POST',
                body: formData,
                signal: controller.signal,
            });
            clearTimeout(timeoutId);

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Upload failed');
            }

            return response.json();
        } catch (error) {
            clearTimeout(timeoutId);
            if (error.name === 'AbortError') {
                throw new Error('Upload request timed out. Check if backend is running.');
            }
            throw error;
        }
    }

    async listDocuments() {
        const response = await fetch(`${API_BASE_URL}/documents/`);
        if (!response.ok) throw new Error('Failed to fetch documents');
        return response.json();
    }

    async startPipeline(filenames, config = {}) {
        const response = await fetch(`${API_BASE_URL}/pipeline/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filenames, config }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Pipeline start failed');
        }

        return response.json();
    }

    async getJobStatus(jobId) {
        const response = await fetch(`${API_BASE_URL}/pipeline/status/${jobId}`);
        if (!response.ok) throw new Error('Failed to fetch job status');
        return response.json();
    }

    async getGraph(jobId) {
        const response = await fetch(`${API_BASE_URL}/graphs/${jobId}`);
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to fetch graph');
        }
        return response.json();
    }

    async getOntology(jobId) {
        const response = await fetch(`${API_BASE_URL}/ontology/${jobId}`);
        if (!response.ok) throw new Error('Failed to fetch ontology');
        return response.json();
    }

    async clearRepository() {
        const response = await fetch(`${API_BASE_URL}/documents/clear`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error('Failed to clear repository');
        return response.json();
    }

    async nadiaChat(jobId, messages, graphData = null, voiceMode = 'none') {
        const body = { job_id: jobId, messages, voice_mode: voiceMode };
        if (graphData) {
            // graphData has structure: { graph: { elements: ... }, stats: ... }
            // Backend expects: { cytoscape: { elements: ... }, stats: ... }
            body.cytoscape = graphData.graph;
            body.stats = graphData.stats;
        }

        const response = await fetch(`${API_BASE_URL}/nadia/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!response.ok) {
            let errorMsg = 'Falha na comunicação com a Nadia';
            try {
                const errorData = await response.json();
                if (errorData.error) errorMsg += `: ${errorData.error}`;
            } catch (e) {
                // Ignore json parse error
            }
            throw new Error(errorMsg);
        }
        return response.json();
    }

    async nadiaAudio(text, voiceMode = 'premium') {
        return fetch(`${API_BASE_URL}/nadia/audio`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, voice_mode: voiceMode }),
        });
    }

    async getNadiaUsage() {
        const response = await fetch(`${API_BASE_URL}/nadia/usage`);
        if (!response.ok) throw new Error('Failed to fetch usage stats');
        return response.json();
    }
}

export const api = new APIClient();
