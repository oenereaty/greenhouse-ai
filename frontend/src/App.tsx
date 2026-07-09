import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import EnvironmentPage from "./pages/EnvironmentPage";
import GrowthPage from "./pages/GrowthPage";
import ControlPage from "./pages/ControlPage";
import ChatPage from "./pages/ChatPage";
import DiaryPage from "./pages/DiaryPage";
import ReportsPage from "./pages/ReportsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/environment" replace />} />
        <Route path="environment" element={<EnvironmentPage />} />
        <Route path="growth" element={<GrowthPage />} />
        <Route path="weather" element={<Navigate to="/environment" replace />} />
        <Route path="prices" element={<Navigate to="/chat" replace />} />
        <Route path="control" element={<ControlPage />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="diary" element={<DiaryPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="*" element={<Navigate to="/environment" replace />} />
      </Route>
    </Routes>
  );
}
