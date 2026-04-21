import { FlatCompat } from '@eslint/eslintrc';

const compat = new FlatCompat({
  baseDirectory: import.meta.dirname,
});

const eslintConfig = [
  ...compat.extends('next/core-web-vitals', 'next/typescript'),
  {
    rules: {
      // Three-font rule backstop. Phase 2.3 will tighten these further
      // (block raw JSX text outside primitive components, etc.).
      'no-restricted-syntax': [
        'warn',
        {
          selector: "Literal[value=/font-family/i]",
          message:
            'Do not inline font-family. Use the <Text>, <Data>, <Title> primitives from components/primitives/.',
        },
      ],
    },
  },
];

export default eslintConfig;
