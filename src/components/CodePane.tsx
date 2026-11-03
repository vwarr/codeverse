import { useRef } from 'react';
import Editor, { OnMount } from '@monaco-editor/react';
import { Button, Text } from '@mantine/core';

const LANGUAGE = 'python';

interface Props {
  starterCode: Record<string, string>;
  onChange: (code: string, language: string) => void;
  // Shown above the editor: the module being debugged, or solution.py.
  fileName: string;
  // When set, a Run tests button sends the editor's current contents.
  onRun?: (code: string) => void;
  running?: boolean;
  runDisabled?: boolean;
}

/** The Python editor. Both tracks are Python only, so there is no language picker. */
export function CodePane({
  starterCode,
  onChange,
  fileName,
  onRun,
  running = false,
  runDisabled = false,
}: Props) {
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);

  const onMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monaco.editor.defineTheme('codeverse', {
      base: 'vs',
      inherit: true,
      rules: [
        { token: 'keyword', foreground: '8A3B12' },
        { token: 'number', foreground: '1D4ED8' },
        { token: 'comment', foreground: '6B6B66' },
      ],
      colors: {
        'editor.background': '#FFFFFF',
        'editorLineNumber.foreground': '#6B6B66',
        'editorLineNumber.activeForeground': '#1A1A19',
        'editor.lineHighlightBackground': '#F6F6F4',
      },
    });
    monaco.editor.setTheme('codeverse');
    onChange(editor.getValue(), LANGUAGE);
  };

  return (
    <>
      <div className="cv-editor-bar">
        <Text size="sm" ff="monospace" c="dimmed">
          {fileName}
        </Text>
        {onRun && (
          <Button
            id="run-tests"
            size="xs"
            h={32}
            variant="default"
            loading={running}
            disabled={runDisabled}
            onClick={() => onRun(editorRef.current?.getValue() ?? '')}
          >
            Run tests
          </Button>
        )}
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        <Editor
          height="100%"
          language={LANGUAGE}
          defaultValue={starterCode[LANGUAGE] ?? ''}
          theme="vs"
          onMount={onMount}
          onChange={(value) => onChange(value ?? '', LANGUAGE)}
          options={{
            minimap: { enabled: false },
            fontSize: 14,
            lineHeight: 24,
            fontFamily: "'IBM Plex Mono', ui-monospace, Menlo, monospace",
            scrollBeyondLastLine: false,
            automaticLayout: true,
            renderLineHighlight: 'line',
            ariaLabel: `Code editor, ${fileName}`,
          }}
        />
      </div>
    </>
  );
}
