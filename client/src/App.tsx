import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { ThemeProvider } from './lib/theme';
import { AppProvider } from './lib/app-context';
import Landing from './pages/Landing';
import Shell from './pages/app/Shell';
import Documents from './pages/app/Documents';
import DocumentWorkspace from './pages/app/DocumentWorkspace';
import PlaybookPage from './pages/app/Playbook';
import MemoryPage from './pages/app/Memory';
import AuditPage from './pages/app/Audit';
import SettingsPage from './pages/app/Settings';

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route
            path="/app/*"
            element={
              <AppProvider>
                <Shell>
                  <Routes>
                    <Route index element={<Documents />} />
                    <Route path="doc/:docId" element={<DocumentWorkspace />} />
                    <Route path="playbook" element={<PlaybookPage />} />
                    <Route path="memory" element={<MemoryPage />} />
                    <Route path="audit" element={<AuditPage />} />
                    <Route path="settings" element={<SettingsPage />} />
                    <Route path="*" element={<Navigate to="/app" replace />} />
                  </Routes>
                </Shell>
              </AppProvider>
            }
          />
          <Route path="/analyze" element={<Navigate to="/app" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}
