// Flat config, replacing .eslintrc.json.
//
// Next 16 removed `next lint`. Running it there does not warn, it parses the
// word "lint" as a project directory and exits 1 with "Invalid project
// directory provided, no such directory: .../lint", which reads like a broken
// path rather than a removed command. `package.json` now calls eslint directly.
//
// eslint-config-next@16 requires eslint >= 9 and exports a flat config array
// rather than an object to `extends`, so the shape here is a spread rather than
// the one-line `"extends": "next/core-web-vitals"` this replaces.
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

const config = [
  {
    // eslint 9 has no .eslintignore. Without this, `eslint .` walks the build
    // output and reports thousands of findings in generated code.
    ignores: ["**/.next/**", "**/out/**", "**/node_modules/**", "next-env.d.ts"],
  },
  ...nextCoreWebVitals,
  {
    rules: {
      // New in eslint-config-next 16, and it lands on 12 existing call sites.
      //
      // It is not wrong: calling setState synchronously inside an effect does
      // cause a second render. But the pattern it flags most often here is the
      // hydration guard next-themes documents:
      //
      //   const [mounted, setMounted] = useState(false);
      //   useEffect(() => setMounted(true), []);
      //
      // which exists precisely to avoid a server/client mismatch and has no
      // one-line replacement. Refactoring twelve effects inside a framework
      // migration would mix a mechanical upgrade with a dozen behaviour-adjacent
      // changes in a live dashboard, and make the whole thing unreviewable.
      //
      // Downgraded rather than disabled, so the sites stay visible and countable
      // instead of disappearing. Tracked in blitzcrieg1/agentmetry#95: work
      // through them one at a time, then delete this block and let the rule
      // error again.
      "react-hooks/set-state-in-effect": "warn",
    },
  },
];

export default config;
