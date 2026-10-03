import js from "@eslint/js";
import globals from "globals";

export default [
  { ignores: ["node_modules/**"] },
  {
    files: ["public/assets/js/**/*.js"],
    languageOptions: { globals: globals.browser },
    rules: {
      ...js.configs.recommended.rules,
      complexity: ["error", 8],
      "max-lines-per-function": [
        "error",
        { max: 40, skipBlankLines: true, skipComments: true },
      ],
      "no-shadow": "error",
      "no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
  {
    files: ["tests/**/*.mjs", "eslint.config.js"],
    languageOptions: { globals: globals.node },
    rules: js.configs.recommended.rules,
  },
];
