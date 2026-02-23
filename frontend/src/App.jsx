import React, { useState } from 'react';
import { Route, Switch, Link } from "wouter";
import UploadPage from './pages/UploadPage';
import VisualizePage from './pages/VisualizePage';
import OntologyPage from './pages/OntologyPage';

// Home page
const Home = () => (
    <div className="max-w-6xl mx-auto px-4 py-16">
        <div className="text-center mb-16">
            <h1 className="text-5xl md:text-6xl font-extrabold mb-6 tracking-tight">
                Plataforma <span className="gradient-text">SGKG</span>
            </h1>
            <p className="text-xl text-seade-gray-dark max-w-2xl mx-auto leading-relaxed">
                Transforme documentos complexos em Grafos de Conhecimento interativos e intuitivos com inteligência artificial de ponta.
            </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            <div className="group relative">
                <div className="absolute -inset-0.5 bg-gradient-to-r from-brand-primary to-brand-accent rounded-2xl blur opacity-25 group-hover:opacity-100 transition duration-1000 group-hover:duration-200"></div>
                <Link href="/upload" className="relative block h-full p-8 bg-white rounded-2xl shadow-premium hover:translate-y-[-4px] transition-all duration-300">
                    <div className="w-14 h-14 bg-indigo-50 rounded-xl flex items-center justify-center text-3xl mb-6 group-hover:scale-110 transition-transform">📤</div>
                    <h3 className="text-2xl font-bold mb-3">Upload de Documentos</h3>
                    <p className="text-seade-gray-dark leading-relaxed">Envie PDFs, CSVs ou textos para extração automática de conhecimento.</p>
                </Link>
            </div>

            <div className="group relative">
                <div className="absolute -inset-0.5 bg-gradient-to-r from-brand-primary to-brand-accent rounded-2xl blur opacity-25 group-hover:opacity-100 transition duration-1000 group-hover:duration-200"></div>
                <Link href="/visualize" className="relative block h-full p-8 bg-white rounded-2xl shadow-premium hover:translate-y-[-4px] transition-all duration-300">
                    <div className="w-14 h-14 bg-indigo-50 rounded-xl flex items-center justify-center text-3xl mb-6 group-hover:scale-110 transition-transform">🔍</div>
                    <h3 className="text-2xl font-bold mb-3">Visualizar Grafos</h3>
                    <p className="text-seade-gray-dark leading-relaxed">Explore conexões e relacionamentos em uma visualização interativa premium.</p>
                </Link>
            </div>

            <div className="group relative">
                <div className="absolute -inset-0.5 bg-gradient-to-r from-brand-primary to-brand-accent rounded-2xl blur opacity-25 group-hover:opacity-100 transition duration-1000 group-hover:duration-200"></div>
                <Link href="/ontology" className="relative block h-full p-8 bg-white rounded-2xl shadow-premium hover:translate-y-[-4px] transition-all duration-300">
                    <div className="w-14 h-14 bg-indigo-50 rounded-xl flex items-center justify-center text-3xl mb-6 group-hover:scale-110 transition-transform">🧠</div>
                    <h3 className="text-2xl font-bold mb-3">Ontologia</h3>
                    <p className="text-seade-gray-dark leading-relaxed">Gerencie o esquema de entidades e tipos de relacionamentos do sistema.</p>
                </Link>
            </div>
        </div>
    </div>
);

function App() {
    const [globalGraphData, setGlobalGraphData] = useState(null);
    const [globalJobId, setGlobalJobId] = useState(null);

    return (
        <div className="min-h-screen bg-seade-gray-light selection:bg-brand-primary/20 selection:text-brand-primary">
            <header className="sticky top-0 z-50 glass-morphism border-b border-gray-200">
                <div className="container mx-auto px-6 h-20 flex justify-between items-center">
                    <Link href="/" className="flex items-center space-x-2">
                        <div className="w-10 h-10 bg-brand-primary rounded-lg flex items-center justify-center text-white font-bold text-xl">SG</div>
                        <span className="text-xl font-bold tracking-tight text-brand-surface group">
                            KG <span className="text-brand-primary transition-colors">Platform</span>
                        </span>
                    </Link>

                    <nav className="hidden md:flex items-center space-x-8">
                        <Link href="/" className="text-sm font-medium text-seade-gray-dark hover:text-brand-primary transition-colors">Início</Link>
                        <Link href="/upload" className="text-sm font-medium text-seade-gray-dark hover:text-brand-primary transition-colors">Upload</Link>
                        <Link href="/visualize" className="text-sm font-medium text-seade-gray-dark hover:text-brand-primary transition-colors">Visualizar</Link>
                        <Link href="/ontology" className="text-sm font-medium text-seade-gray-dark hover:text-brand-primary transition-colors">Ontologia</Link>
                    </nav>
                </div>
            </header>

            <main>
                <Switch>
                    <Route path="/" component={Home} />
                    <Route path="/upload">
                        {() => <UploadPage setGlobalGraphData={setGlobalGraphData} setGlobalJobId={setGlobalJobId} />}
                    </Route>
                    <Route path="/visualize">
                        {() => <VisualizePage globalGraphData={globalGraphData} globalJobId={globalJobId} setGlobalGraphData={setGlobalGraphData} setGlobalJobId={setGlobalJobId} />}
                    </Route>
                    <Route path="/ontology">
                        {() => <OntologyPage globalGraphData={globalGraphData} globalJobId={globalJobId} />}
                    </Route>
                    <Route>
                        <div className="flex flex-col items-center justify-center h-[70vh]">
                            <h2 className="text-4xl font-bold mb-4">404: Página não encontrada</h2>
                            <Link href="/" className="text-brand-primary underline">Voltar para o início</Link>
                        </div>
                    </Route>
                </Switch>
            </main>
        </div>
    );
}

export default App;
