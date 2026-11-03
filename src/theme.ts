import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Code,
  createTheme,
  InputWrapper,
  MantineColorsTuple,
  Paper,
  Radio,
  Select,
  Table,
  Title,
} from '@mantine/core';

// Design tokens. Text colours meet 4.5:1 on every surface they are used on:
// #1A1A19 and #5E5E5A on #F6F6F4 / #FFFFFF / #ECECE8; the accent only on #F6F6F4 / #FFFFFF.
export const tokens = {
  bg: '#F6F6F4',
  surface: '#FFFFFF',
  surfaceMuted: '#ECECE8',
  text: '#1A1A19',
  muted: '#5E5E5A',
  border: '#DADAD5',
  borderStrong: '#B9B9B3',
  accent: '#C2410C',
  inkHover: '#3A3A38',
} as const;

// Primary is "ink": dark buttons. Index 8/9 are the hover/filled shades Mantine uses.
const ink: MantineColorsTuple = [
  '#F6F6F4',
  '#ECECE8',
  '#DADAD5',
  '#B9B9B3',
  '#8A8A85',
  '#5E5E5A',
  '#3A3A38',
  '#2A2A28',
  '#1A1A19',
  '#3A3A38',
];

const accent: MantineColorsTuple = [
  '#FFF4ED',
  '#FFE6D5',
  '#FECCAA',
  '#FDAC74',
  '#FB8A3C',
  '#F97316',
  '#EA580C',
  '#C2410C',
  '#9A3412',
  '#7C2D12',
];

export const theme = createTheme({
  fontFamily: "'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', sans-serif",
  fontFamilyMonospace: "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace",
  headings: {
    fontFamily: "'IBM Plex Sans', system-ui, sans-serif",
    fontWeight: '600',
    sizes: {
      h1: { fontSize: '30px', lineHeight: '1.2' },
      h2: { fontSize: '15px', lineHeight: '1.4' },
      h3: { fontSize: '14px', lineHeight: '1.4' },
    },
  },
  colors: { ink, accent },
  primaryColor: 'ink',
  primaryShade: 8,
  black: tokens.text,
  white: tokens.surface,
  defaultRadius: 'sm',
  radius: { xs: '2px', sm: '4px', md: '4px', lg: '4px', xl: '4px' },
  shadows: { xs: 'none', sm: 'none', md: 'none', lg: 'none', xl: 'none' },
  focusRing: 'auto',
  cursorType: 'pointer',
  components: {
    Button: Button.extend({
      defaultProps: { radius: 'sm', fw: 500 },
      classNames: { root: 'cv-button' },
    }),
    Card: Card.extend({
      defaultProps: { radius: 'sm', withBorder: true, shadow: 'none', padding: 'lg' },
    }),
    Paper: Paper.extend({ defaultProps: { radius: 'sm', shadow: 'none' } }),
    Select: Select.extend({
      defaultProps: {
        radius: 'sm',
        size: 'md',
        comboboxProps: { shadow: 'none', radius: 'sm' },
      },
    }),
    Radio: Radio.extend({
      defaultProps: { color: 'accent.7', size: 'sm' },
      classNames: { radio: 'cv-radio' },
    }),
    InputWrapper: InputWrapper.extend({
      classNames: { label: 'cv-label', description: 'cv-description' },
    }),
    Badge: Badge.extend({ defaultProps: { radius: 'sm', variant: 'outline', color: 'ink.8' } }),
    Alert: Alert.extend({ defaultProps: { radius: 'sm', variant: 'outline' } }),
    Code: Code.extend({ classNames: { root: 'cv-code' } }),
    Table: Table.extend({ defaultProps: { verticalSpacing: 10, horizontalSpacing: 0 } }),
    Title: Title.extend({ defaultProps: { c: tokens.text } }),
    Anchor: Anchor.extend({ defaultProps: { c: tokens.text, underline: 'always' } }),
  },
});
