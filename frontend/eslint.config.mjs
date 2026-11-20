export default [
  { ignores: ['dist/**', 'test-results/**', 'node_modules/**'] },
  {
    files: ['**/*.mjs'],
    languageOptions: { ecmaVersion: 'latest', sourceType: 'module' },
    rules: {
      'no-dupe-keys': 'error',
      'no-unreachable': 'error',
      'no-constant-binary-expression': 'error',
      'no-unused-vars': 'error',
    },
  },
];
