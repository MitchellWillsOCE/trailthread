import fs from "node:fs";

/** Prefer `path.new` when the primary DB is locked during a hot rebuild. */
export function resolveSqlitePath(primaryPath) {
  const altPath = `${primaryPath}.new`;
  if (!fs.existsSync(altPath)) {
    return primaryPath;
  }
  if (!fs.existsSync(primaryPath)) {
    return altPath;
  }
  const altMtime = fs.statSync(altPath).mtimeMs;
  const primaryMtime = fs.statSync(primaryPath).mtimeMs;
  return altMtime >= primaryMtime ? altPath : primaryPath;
}
