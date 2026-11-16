import { QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { useState, type PropsWithChildren } from "react";
import { BrowserRouter } from "react-router";
import { createAdminQueryClient } from "./query-client";

export default function AppProviders({ children }: PropsWithChildren) {
  return (
    <ConfigProvider locale={zhCN}>
      <AntApp>
        <AdminQueryProvider>
          <BrowserRouter>{children}</BrowserRouter>
        </AdminQueryProvider>
      </AntApp>
    </ConfigProvider>
  );
}

function AdminQueryProvider({ children }: PropsWithChildren) {
  const { message } = AntApp.useApp();
  const [queryClient] = useState(() =>
    createAdminQueryClient((content) => {
      void message.error(content);
    }),
  );

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
