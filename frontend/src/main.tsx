import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.tsx';
import {RecommendationProvider} from './state/RecommendationContext';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RecommendationProvider>
      <App />
    </RecommendationProvider>
  </StrictMode>,
);
