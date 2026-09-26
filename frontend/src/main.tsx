import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { CameraProvider } from './hooks/useCamera'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/*
      The camera provider is mounted ABOVE <App /> on purpose. It owns the only
      camera state and the only status poll, so it must not be torn down and
      rebuilt by a view change — otherwise every route would re-poll the camera
      and a start request could be re-issued on navigation.
    */}
    <CameraProvider>
      <App />
    </CameraProvider>
  </StrictMode>,
)
