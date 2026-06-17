import { createRoot } from 'react-dom/client';
import { App } from './App';
import { initColorScheme } from './lib/color-scheme';
import { AppProviders } from './providers/AppProviders';
import './styles/app.css';

initColorScheme();

const rootEl = document.getElementById('root');
if (rootEl) {
  createRoot(rootEl).render(
    <AppProviders>
      <App />
    </AppProviders>,
  );
}
