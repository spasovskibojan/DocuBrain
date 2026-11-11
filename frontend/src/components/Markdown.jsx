import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const components = {
  table: ({ children }) => (
    <div className="table-responsive">
      <table className="table table-sm table-bordered align-middle mb-2">{children}</table>
    </div>
  ),
};

export default function Markdown({ children }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children || ''}
      </ReactMarkdown>
    </div>
  );
}
