import type { Metadata } from "next";
import Shell from "@/components/Shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "FNOL Claims Desk",
  description: "First Notice of Loss intake: OCR, AI extraction with confidence, validation, human review.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: "try{if(localStorage.getItem('fnol_theme')==='dark')document.documentElement.classList.add('dark')}catch(e){}" }} />
      </head>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
