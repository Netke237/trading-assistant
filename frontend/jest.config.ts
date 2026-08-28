import type { Config } from 'jest';

const config: Config = {
  preset: 'ts-jest',
  testEnvironment: 'jsdom',
  moduleNameMapper: {
    // Order matters — Jest uses the first matching pattern. This must come
    // before the '@/' alias rule below: a CSS-module import written via the
    // alias (e.g. ContractStar importing WatchStar's CSS as
    // '@/components/atoms/WatchStar/WatchStar.module.css') would otherwise
    // match '^@/(.*)$' first and resolve to the real .css file instead of
    // the mock, crashing with a JS-parse error on real CSS syntax.
    '\\.module\\.css$': '<rootDir>/__mocks__/styleMock.js',
    '^@/(.*)$': '<rootDir>/$1',
  },
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  testPathIgnorePatterns: ['/node_modules/', '/e2e/'],
  transform: {
    '^.+\\.tsx?$': ['ts-jest', { tsconfig: { jsx: 'react-jsx' } }],
  },
};

export default config;
