import IORedis from 'ioredis';
import { IntakeContractError, IntakeHmacKeys, parseAndVerifyLegacyJobRequest, StreamFields } from './legacyIntakeContract';
import { IntakePersistenceError, LegacyJobIntakeRepository } from './legacyJobIntakeRepository';

export interface LegacyIntakeConsumerSettings {
  stream: string;
  group: string;
  consumer: string;
  deadLetterStream: string;
  maxDeliveries: number;
}

/**
 * Redis Streams consumer with manual acknowledgement. It is intentionally not
 * imported by main.ts yet: D2a can be tested and deployed dormant before the
 * explicit Stream B activation gate.
 */
export class LegacyIntakeConsumer {
  constructor(
    private readonly redis: IORedis,
    private readonly repository: LegacyJobIntakeRepository,
    private readonly keys: IntakeHmacKeys,
    private readonly settings: LegacyIntakeConsumerSettings,
  ) {}

  async ensureGroup(): Promise<void> {
    try {
      await this.redis.xgroup('CREATE', this.settings.stream, this.settings.group, '0', 'MKSTREAM');
    } catch (error) {
      if (!(error instanceof Error) || !error.message.includes('BUSYGROUP')) throw error;
    }
  }

  async consumeOnce(blockMs = 1_000): Promise<number> {
    const result = await this.redis.xreadgroup(
      'GROUP', this.settings.group, this.settings.consumer,
      'COUNT', 10,
      'BLOCK', blockMs,
      'STREAMS', this.settings.stream, '>',
    ) as unknown as Array<[string, Array<[string, string[]]>]> | null;
    if (!result) return 0;
    let handled = 0;
    for (const [, entries] of result) {
      for (const [entryId, fieldPairs] of entries) {
        await this.handle(entryId, fieldPairsToObject(fieldPairs));
        handled += 1;
      }
    }
    return handled;
  }

  private async handle(entryId: string, fields: StreamFields): Promise<void> {
    try {
      const request = parseAndVerifyLegacyJobRequest(fields, this.keys);
      await this.repository.persist(request);
      await this.redis.xack(this.settings.stream, this.settings.group, entryId);
    } catch (error) {
      if (error instanceof IntakeContractError || error instanceof IntakePersistenceError) {
        await this.deadLetterThenAck(entryId, fields, error.code);
        return;
      }
      // Transient MySQL/Redis failures stay in the PEL for XAUTOCLAIM recovery.
      throw error;
    }
  }

  private async deadLetterThenAck(entryId: string, fields: StreamFields, reasonCode: string): Promise<void> {
    const deadLetterFields: StreamFields = {
      ...fields,
      original_stream: this.settings.stream,
      original_entry_id: entryId,
      reason_code: reasonCode,
    };
    await this.redis.xadd(
      this.settings.deadLetterStream,
      '*',
      ...Object.entries(deadLetterFields).flatMap(([key, value]) => [key, value]),
    );
    await this.redis.xack(this.settings.stream, this.settings.group, entryId);
  }
}

function fieldPairsToObject(fieldPairs: string[]): StreamFields {
  const fields: StreamFields = {};
  for (let index = 0; index < fieldPairs.length; index += 2) {
    fields[fieldPairs[index]] = fieldPairs[index + 1];
  }
  return fields;
}
