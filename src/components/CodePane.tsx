import { useEffect, useRef, useState } from 'react';
import Editor, { OnMount } from '@monaco-editor/react';
import { Group, Select, useMantineColorScheme } from '@mantine/core';

export const LANGUAGES = [
  { value: 'python', label: 'Python' },
  { value: 'javascript', label: 'JavaScript' },
  { value: 'typescript', label: 'TypeScript' },
  { value: 'java', label: 'Java' },
  { value: 'cpp', label: 'C++' },
];

interface Props {
  initialLanguage: string;
  starterCode: Record<string, string>;
  onChange: (code: string, language: string) => void;
  height?: string;
}

export function CodePane({ initialLanguage, starterCode, onChange, height = '100%' }: Props) {
  const { colorScheme } = useMantineColorScheme();
  const [language, setLanguage] = useState(initialLanguage);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const lastStarter = useRef<string>(starterCode[initialLanguage] ?? '');

  const onMount: OnMount = (editor) => {
    editorRef.current = editor;
    onChange(editor.getValue(), language);
  };

  // Switching language swaps in that language's starter unless the candidate already wrote something.
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) {
      return;
    }
    const current = editor.getValue();
    const untouched = current.trim() === '' || current === lastStarter.current;
    const next = starterCode[language] ?? '';
    if (untouched) {
      editor.setValue(next);
      lastStarter.current = next;
    }
    onChange(editor.getValue(), language);
  }, [language]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height }}>
      <Group justify="flex-end" p="xs">
        <Select
          id="language-select"
          size="xs"
          data={LANGUAGES}
          value={language}
          onChange={(v) => v && setLanguage(v)}
          allowDeselect={false}
          w={150}
        />
      </Group>
      <div style={{ flex: 1, minHeight: 0 }}>
        <Editor
          height="100%"
          language={language}
          defaultValue={starterCode[initialLanguage] ?? ''}
          theme={colorScheme === 'dark' ? 'vs-dark' : 'vs'}
          onMount={onMount}
          onChange={(value) => onChange(value ?? '', language)}
          options={{
            minimap: { enabled: false },
            fontSize: 14,
            scrollBeyondLastLine: false,
            automaticLayout: true,
          }}
        />
      </div>
    </div>
  );
}
