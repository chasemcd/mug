/**
 * Typed identifiers and the active kind registry.
 *
 * A MUG identifier is `<kind>_<canonical lowercase UUIDv7>`. The kind prefix
 * names the resource type; the UUIDv7 body gives database locality only and is
 * never a trusted time, order, or entropy source. This is the browser-side twin
 * of `mug.kernel.ids`; the registry below mirrors the Python one row for row, and
 * a conformance vector cross-checks the two.
 */

/** One row of the active identifier registry. */
export interface IdKind {
  readonly prefix: string;
  readonly typeName: string;
  readonly resourceClass: string;
  readonly owner: string;
}

// The canonical UUIDv7 body: version nibble 7, variant nibble 8/9/a/b.
export const UUIDV7 = '[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}';

// The active kinds (identifiers-and-resource-hierarchy.md). Order follows the
// documented registry table and the Python `ID_KIND_REGISTRY`.
export const ID_KIND_REGISTRY: readonly IdKind[] = [
  { prefix: 'study', typeName: 'StudyId', resourceClass: 'definition', owner: 'API-01' },
  { prefix: 'studyver', typeName: 'StudyVersionId', resourceClass: 'immutable-version', owner: 'API-01' },
  { prefix: 'flownode', typeName: 'FlowNodeDefinitionId', resourceClass: 'definition', owner: 'API-01/04' },
  { prefix: 'deploy', typeName: 'DeploymentId', resourceClass: 'mutable-resource', owner: 'API-02' },
  { prefix: 'deployrev', typeName: 'DeploymentRevisionId', resourceClass: 'immutable-version', owner: 'API-02' },
  { prefix: 'participant', typeName: 'ParticipantPrincipalId', resourceClass: 'principal', owner: 'API-03' },
  { prefix: 'service', typeName: 'ServicePrincipalId', resourceClass: 'principal', owner: 'kernel' },
  { prefix: 'system', typeName: 'SystemPrincipalId', resourceClass: 'principal', owner: 'kernel' },
  { prefix: 'researcher', typeName: 'ResearcherPrincipalId', resourceClass: 'principal', owner: 'API-03' },
  { prefix: 'enrollment', typeName: 'EnrollmentId', resourceClass: 'mutable-resource', owner: 'API-03' },
  { prefix: 'visit', typeName: 'VisitId', resourceClass: 'runtime-occurrence', owner: 'API-04' },
  { prefix: 'visitplan', typeName: 'VisitPlanId', resourceClass: 'immutable-materialization', owner: 'API-04' },
  { prefix: 'activitydef', typeName: 'ActivityDefinitionId', resourceClass: 'definition', owner: 'API-01/04' },
  { prefix: 'activity', typeName: 'ActivityOccurrenceId', resourceClass: 'runtime-occurrence', owner: 'API-04' },
  { prefix: 'seatdef', typeName: 'SeatDefinitionId', resourceClass: 'definition', owner: 'API-05' },
  { prefix: 'actor', typeName: 'ActorInstanceId', resourceClass: 'runtime-occurrence', owner: 'API-05' },
  { prefix: 'controller', typeName: 'ControllerBindingId', resourceClass: 'runtime-occurrence', owner: 'API-05' },
  { prefix: 'interaction', typeName: 'InteractionId', resourceClass: 'runtime-occurrence', owner: 'API-06' },
  { prefix: 'group', typeName: 'GroupId', resourceClass: 'runtime-occurrence', owner: 'API-06' },
  { prefix: 'channeldef', typeName: 'ChannelDefinitionId', resourceClass: 'definition', owner: 'API-06' },
  { prefix: 'channel', typeName: 'ChannelInstanceId', resourceClass: 'runtime-occurrence', owner: 'API-06' },
  { prefix: 'lease', typeName: 'LeaseId', resourceClass: 'runtime-occurrence', owner: 'API-06' },
  { prefix: 'leaseepoch', typeName: 'LeaseNamespaceEpochId', resourceClass: 'runtime-occurrence', owner: 'API-06' },
  { prefix: 'prodepoch', typeName: 'ProducerEpochId', resourceClass: 'runtime-occurrence', owner: 'API-09/10' },
  { prefix: 'clockepoch', typeName: 'ClockEpochId', resourceClass: 'runtime-occurrence', owner: 'kernel' },
  { prefix: 'correlation', typeName: 'CorrelationId', resourceClass: 'runtime-occurrence', owner: 'kernel' },
  { prefix: 'episode', typeName: 'EpisodeId', resourceClass: 'runtime-occurrence', owner: 'API-07' },
  { prefix: 'message', typeName: 'MessageId', resourceClass: 'runtime-occurrence', owner: 'API-08' },
  { prefix: 'stream', typeName: 'StreamId', resourceClass: 'mutable-append-resource', owner: 'API-10' },
  { prefix: 'event', typeName: 'EventId', resourceClass: 'runtime-occurrence', owner: 'API-10' },
  { prefix: 'artifact', typeName: 'ArtifactId', resourceClass: 'runtime-occurrence', owner: 'API-11' },
  { prefix: 'upload', typeName: 'UploadId', resourceClass: 'runtime-occurrence', owner: 'API-11' },
  { prefix: 'agentdef', typeName: 'AgentDefinitionId', resourceClass: 'definition', owner: 'API-12' },
  { prefix: 'agentver', typeName: 'AgentVersionId', resourceClass: 'immutable-version', owner: 'API-12' },
  { prefix: 'agentrun', typeName: 'AgentRunId', resourceClass: 'runtime-occurrence', owner: 'API-12' },
  { prefix: 'promptdef', typeName: 'PromptTemplateDefinitionId', resourceClass: 'definition', owner: 'API-12' },
  { prefix: 'promptver', typeName: 'PromptTemplateVersionId', resourceClass: 'immutable-version', owner: 'API-12' },
  { prefix: 'decision', typeName: 'DecisionId', resourceClass: 'runtime-occurrence', owner: 'API-12' },
  { prefix: 'modelcall', typeName: 'ModelInvocationId', resourceClass: 'runtime-occurrence', owner: 'API-13' },
  { prefix: 'generation', typeName: 'ModelGenerationId', resourceClass: 'runtime-occurrence', owner: 'API-13' },
  { prefix: 'tooldef', typeName: 'ToolDefinitionId', resourceClass: 'definition', owner: 'API-14' },
  { prefix: 'toolver', typeName: 'ToolVersionId', resourceClass: 'immutable-version', owner: 'API-14' },
  { prefix: 'toolcall', typeName: 'ToolCallId', resourceClass: 'runtime-occurrence', owner: 'API-14' },
  { prefix: 'memory', typeName: 'MemorySnapshotId', resourceClass: 'immutable-materialization', owner: 'API-15' },
  { prefix: 'prefdef', typeName: 'PreferenceProtocolDefinitionId', resourceClass: 'definition', owner: 'API-18' },
  { prefix: 'prefver', typeName: 'PreferenceProtocolVersionId', resourceClass: 'immutable-version', owner: 'API-18' },
  { prefix: 'prefquery', typeName: 'PreferenceQueryId', resourceClass: 'runtime-occurrence', owner: 'API-18' },
  { prefix: 'prefassign', typeName: 'PreferenceAssignmentId', resourceClass: 'runtime-occurrence', owner: 'API-18' },
  { prefix: 'prefresponse', typeName: 'PreferenceResponseId', resourceClass: 'runtime-occurrence', owner: 'API-18' },
  { prefix: 'secret', typeName: 'SecretBindingId', resourceClass: 'mutable-resource', owner: 'API-02' },
  { prefix: 'job', typeName: 'JobId', resourceClass: 'runtime-occurrence', owner: 'API-22' },
  { prefix: 'command', typeName: 'CommandId', resourceClass: 'runtime-occurrence', owner: 'kernel' },
  { prefix: 'request', typeName: 'RequestId', resourceClass: 'runtime-occurrence', owner: 'kernel' },
  { prefix: 'receipt', typeName: 'ReceiptId', resourceClass: 'runtime-occurrence', owner: 'kernel' },
  { prefix: 'error', typeName: 'ErrorId', resourceClass: 'runtime-occurrence', owner: 'kernel' },
];

/** Every active prefix, for a quick membership test. */
export const ACTIVE_ID_PREFIXES: ReadonlySet<string> = new Set(
  ID_KIND_REGISTRY.map((kind) => kind.prefix),
);

// Prefixes retired by ADR-0013/0014/0015. They are reserved forever: never
// reissued, never valid on the wire.
export const RESERVED_ID_PREFIXES: ReadonlySet<string> = new Set([
  'studydraft',
  'draftrev',
  'account',
  'authsession',
  'wavedef',
  'retpolicy',
  'retpolicyver',
]);

// The union of every active prefix (schema `RegisteredMugId`).
const REGISTERED_ID_PATTERN = new RegExp(
  '^(?:' + ID_KIND_REGISTRY.map((kind) => kind.prefix).join('|') + ')_' + UUIDV7 + '$',
);

/** Return the anchored regular expression source for one kind of identifier. */
export function idPattern(prefix: string): string {
  return '^' + prefix + '_' + UUIDV7 + '$';
}

/** Report whether a string is a well-formed identifier of any active kind. */
export function isRegisteredId(value: string): boolean {
  return REGISTERED_ID_PATTERN.test(value);
}

/** Report whether a string is a well-formed identifier of exactly one kind. */
export function isId(prefix: string, value: string): boolean {
  return new RegExp(idPattern(prefix)).test(value);
}

/** The kind prefix and the UUIDv7 body of an identifier. */
export interface ParsedId {
  readonly kind: string;
  readonly uuid: string;
}

/**
 * Split a registered identifier into its kind and UUIDv7 body.
 *
 * It returns `null` for anything that is not a well-formed identifier of an
 * active kind, so a caller never trusts a malformed or retired identifier.
 */
export function parseId(value: string): ParsedId | null {
  if (!isRegisteredId(value)) {
    return null;
  }
  const separator = value.indexOf('_');
  return { kind: value.slice(0, separator), uuid: value.slice(separator + 1) };
}
