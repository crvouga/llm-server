import { createRoot } from 'react-dom/client';
import { App } from './App';
import { AppProviders } from './providers/AppProviders';
import './styles/app.css';

const rootEl = document.getElementById('root');
if (rootEl) {
  createRoot(rootEl).render(
    <AppProviders>
      <App />
    </AppProviders>,
  );
}
