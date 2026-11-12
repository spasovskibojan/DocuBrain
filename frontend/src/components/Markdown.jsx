import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const components = {
  table: ({ children }) => (
    <div className="table-responsive">
      <table className="table table-sm table-bordered align-middle mb-2">{children}</table>
    </div>
  ),
};

// Turns [n] markers into links so they can be rendered as citation chips
function linkCitations(text, sources) {
  if (!sources?.length) return text;
  return text.replace(/\[(\d+)\](?!\()/g, (marker, n) =>
    sources[n - 1] ? `[${n}](#source-${n})` : marker
  );
}

export default function Markdown({ children, sources }) {
  const citationComponents = {
    ...components,
    a: ({ href, children: label, ...props }) => {
      if (href?.startsWith('#source-')) {
        const source = sources[Number(href.slice(8)) - 1];
        return (
          <sup className="citation" title={`${source.document_name} (Pg ${source.page_number})\n\n${source.chunk_text}`}>
            {label}
          </sup>
        );
      }
      return <a href={href} {...props}>{label}</a>;
    },
  };

  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={citationComponents}>
        {linkCitations(children || '', sources)}
      </ReactMarkdown>
    </div>
  );
}
