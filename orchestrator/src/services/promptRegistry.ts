import prisma from '../database/db';

export type ResolvedPrompt = {
  content: string;
  config: Record<string, unknown>;
  version: number | null;
};

export async function resolveProductionPromptWithConfig(
  key: string,
  variables: Record<string, string>,
  fallback: string,
  fallbackConfig: Record<string, unknown> = {},
): Promise<ResolvedPrompt> {
  try {
    const template = await prisma.agentPromptTemplate.findUnique({ where: { prompt_key: key } });
    if (!template?.production_version) return { content: fallback, config: fallbackConfig, version: null };
    const version = await prisma.agentPromptVersion.findUnique({
      where: { prompt_template_id_version: { prompt_template_id: template.id, version: template.production_version } },
    });
    if (!version?.content) return { content: fallback, config: fallbackConfig, version: null };
    const config = version.config_json && typeof version.config_json === 'object' && !Array.isArray(version.config_json)
      ? version.config_json as Record<string, unknown>
      : {};
    return {
      content: version.content.replace(/{{\s*([a-zA-Z0-9_]+)\s*}}/g, (_, name) => variables[name] ?? ''),
      config,
      version: version.version,
    };
  } catch (error) {
    console.warn(`[PromptRegistry] Falling back for ${key}:`, error);
    return { content: fallback, config: fallbackConfig, version: null };
  }
}

/** Reads only the version explicitly promoted by an administrator. */
export async function resolveProductionPrompt(
  key: string,
  variables: Record<string, string>,
  fallback: string,
): Promise<string> {
  return (await resolveProductionPromptWithConfig(key, variables, fallback)).content;
}
