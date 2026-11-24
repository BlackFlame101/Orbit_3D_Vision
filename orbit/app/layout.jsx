import './globals.css';

export const metadata = {title: 'Orbit · Photo to form', description: 'Orbit Phase 5 frontend prototype. No GPU inference.'};

export default function RootLayout({children}) {
  return <html lang="en"><body><noscript><p className="notice">Enable JavaScript to use the Orbit frontend prototype.</p></noscript>{children}</body></html>;
}
