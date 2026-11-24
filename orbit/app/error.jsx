'use client';
export default function ErrorPage({reset}) {
  return <section className="notice" role="alert"><h1>The workspace could not be displayed.</h1><p>Your files have not been uploaded to a server.</p><button onClick={reset}>Try again</button></section>;
}
