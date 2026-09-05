// Run pinned upstream VRCX functions against synthetic inputs and in-memory SQLite.
// Node >= 22.13 required. Never opens a user's VRCX database or VRChat logs.
// Usage: node scripts/probe_vrcx_source_contract.cjs SOURCE_DIR [--fetch] [--report FILE]
// --fetch downloads only the pinned files below; all outputs must stay in this repo.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');
const vm = require('node:vm');
const { DatabaseSync } = require('node:sqlite');

const COMMIT = 'eafcccb20ed5828d99bd1b0f4b53a384a52a1d47';
const SOURCES = {
    'src/stores/gameLog/mediaParsers.js': 'f1a2aec70323773987ce69b41e5f847611f4da405e7d34f6de59054d33eb3c29',
    'src/stores/gameLog/index.js': 'b83e1fc2392ee165b2137c863dd23a1ea67f891f84bdc6d4768c719f307695c1',
    'src/services/database/index.js': '338a21d6e10666862aa2ad3f303bd655cfb77cf18848f4d41d219e6a44e035fe',
    'src/services/database/gameLog.js': '1c77cbdb84769e7ecb2c8192e9367c72cf9a25ef74fa88cd26833178f1038b16',
    'src/shared/utils/user.js': '732aef0dbe2c8f50b4705c0e769824e574a0882764f44170cec6f8c399242460',
    'src/shared/utils/world.js': 'eb212e16957d9d37d91fc87561902c7b6ae750b596be51b5be4b7eb3afe93390',
    'src/shared/utils/locationParser.js': '024f227c2fffcdb54d302617b5198ddc73e947453d96b93ef109505a3949e17f',
    'src/shared/utils/base/string.js': '8dc47656c629beb454f3700b9b7de18a78766b85606cae920a10643a267e7c48',
    'src/shared/constants/world.js': '7021860a4ef722783418b61f1c0be0ab59fea6d1a415cc35980276d1ab324eff',
    'src/coordinators/gameLogCoordinator.js': '3b2e2a34b55cb043f703b4a5e8de834912ab70087a8f6d59bb3dbb8da0aff85d'
};
const ROOT = path.resolve(__dirname, '..');
const BASE_TIME = Date.parse('2026-07-18T12:00:00.000Z');
const URL_A = 'https://api.udon.dance/api/songs/play?id=7&node=a';
const URL_B = 'https://api.udon.dance/api/songs/play?id=7&node=b';
const ROOM = 'wrld_00000000-0000-0000-0000-000000000000:123~region(jp)';
const RPC_ROOM = 'wrld_f20326da-f1ac-45fc-a062-609723b097b1:123';
const at = seconds => new Date(BASE_TIME + seconds * 1000).toISOString();
const plain = value => JSON.parse(JSON.stringify(value));

function repoPath(input) {
    const resolved = path.resolve(input);
    const relative = path.relative(ROOT, resolved);
    assert(relative && !relative.startsWith('..') && !path.isAbsolute(relative),
        'Source cache and report must be inside the repository');
    return resolved;
}

// These extract whole, unchanged functions from hash-verified source. Matching
// closing indentation is deliberate: this probe is pinned, not a JS parser.
function extract(source, name, method = false) {
    const match = new RegExp(`^([ \\t]*)${method ? '' : 'function '}${name}\\(`, 'm').exec(source);
    assert(match, `Missing upstream function: ${name}`);
    const rest = source.slice(match.index);
    const end = new RegExp(`^${match[1]}}${method ? ',' : ''}\\r?$`, 'm').exec(rest);
    assert(end, `Missing function end: ${name}`);
    return rest.slice(0, end.index + end[0].length).trim().replace(/,$/, '');
}

function environment(source, elapsedSeconds = 0) {
    let clockMs = BASE_TIME + elapsedSeconds * 1000;
    class ProbeDate extends Date {
        static now() { return clockMs; }
    }
    const db = new DatabaseSync(':memory:');
    const schema = source['src/services/database/index.js'].match(
        /`(CREATE TABLE IF NOT EXISTS gamelog_video_play [^`]+)`/)[1];
    db.exec(schema);
    const attempts = [];
    const timers = [];
    const nowPlaying = { value: { url: '', playing: false } };
    const cachedUsers = new Map([
        ['usr_alice', { id: 'usr_alice', displayName: 'Alice' }],
        ['usr_bob', { id: 'usr_bob', displayName: 'Bob' }]
    ]);
    const sandbox = {
        Date: ProbeDate, URL, structuredClone,
        // Console errors fail the probe instead of silently hiding bad fixtures.
        console: { error: (...args) => { throw new Error(args.join(' ')); } },
        nowPlaying, userStore: { cachedUsers, cachedUserIdsByDisplayName: new Map() },
        advancedSettingsStore: { youTubeApi: false },
        vrStore: { updateVrNowPlaying() {} },
        notificationStore: { queueGameLogNoty() {} },
        addGameLog() {}, formatSeconds: String,
        workerTimers: { setTimeout: callback => timers.push(callback) },
        convertYoutubeTime: () => { throw new Error('YouTube API outside probe scope'); },
        sqliteService: { executeNonQuery(sql, parameters) {
            attempts.push(plain(parameters));
            db.prepare(sql).run(parameters);
        } }
    };
    const helpers = [
        extract(source['src/shared/utils/user.js'], 'findUserByDisplayName'),
        extract(source['src/shared/utils/locationParser.js'], 'parseLocation'),
        extract(source['src/shared/utils/world.js'], 'isRpcWorld'),
        extract(source['src/shared/utils/base/string.js'], 'replaceBioSymbols'),
        source['src/shared/constants/world.js'].replace(/export \{ rpcWorlds \};/, '')
    ].join('\n');
    const store = source['src/stores/gameLog/index.js'];
    const functions = ['clearNowPlaying', 'setNowPlaying', 'updateNowPlaying']
        .map(name => extract(store, name)).join('\n');
    const parser = source['src/stores/gameLog/mediaParsers.js']
        .replace(/^import \{[\s\S]+?\} from [^;]+;/, '')
        .replace('export function createMediaParsers', 'function createMediaParsers');
    const insert = extract(source['src/services/database/gameLog.js'],
        'addGamelogVideoPlayToDatabase', true);
    const coordinator = source['src/coordinators/gameLogCoordinator.js'];
    const genericCase = coordinator.slice(coordinator.indexOf("case 'video-play':"),
        coordinator.indexOf("case 'video-sync':"));
    assert(genericCase.includes('decodeURI') && genericCase.includes('lastVideoUrl'));
    vm.runInNewContext(`${helpers}\nconst database = {${insert}};\n${functions}\n${parser}
        const parsers = createMediaParsers({ nowPlaying, setNowPlaying, clearNowPlaying,
            userStore, advancedSettingsStore });
        const gameLogStore = { ...parsers, lastVideoUrl: '',
            setLastVideoUrl(url) { this.lastVideoUrl = url; } };
        function dispatchGeneric(gameLog, location, userId = '') {
            switch (gameLog.type) { ${genericCase} }
        }
        globalThis.probe = { ...parsers, clearNowPlaying, updateNowPlaying,
            dispatchGeneric, database, gameLogStore };
    `, sandbox, { timeout: 5000, filename: 'pinned-vrcx-source-probe.js' });
    return {
        ...sandbox.probe, db, attempts, nowPlaying, cachedUsers, timers,
        rows: () => plain(db.prepare('SELECT * FROM gamelog_video_play ORDER BY id').all()),
        setClock: seconds => { clockMs = BASE_TIME + seconds * 1000; },
        pypy({ time = 0, url = URL_A, pos = 0, length = 300,
            title = '$7. Test (Alice)', room = ROOM } = {}) {
            sandbox.probe.addGameLogPyPyDance({ dt: at(time),
                data: `VideoPlay(PyPyDance) "${url}",${pos},${length},"${title}"` }, room);
        },
        generic({ time = 0, url = URL_A, room = ROOM, name, videoId } = {}) {
            sandbox.probe.dispatchGeneric({ dt: at(time), type: 'video-play',
                videoUrl: url, displayName: name, videoId }, room);
        }
    };
}

async function main() {
    const args = process.argv.slice(2);
    assert(args[0] && !args[0].startsWith('--'), 'Expected SOURCE_DIR');
    const sourceDir = repoPath(args.shift());
    let download = false;
    let reportPath;
    while (args.length) {
        const arg = args.shift();
        if (arg === '--fetch') download = true;
        else if (arg === '--report' && args[0]) reportPath = repoPath(args.shift());
        else throw new Error(`Unknown argument: ${arg}`);
    }
    if (download) await fs.mkdir(sourceDir, { recursive: true });
    const source = {};
    for (const [upstreamPath, expectedHash] of Object.entries(SOURCES)) {
        const cached = path.join(sourceDir, upstreamPath.replaceAll('/', '_'));
        let bytes;
        try { bytes = await fs.readFile(cached); }
        catch (error) {
            if (error.code !== 'ENOENT' || !download) throw error;
            const response = await fetch(
                `https://raw.githubusercontent.com/vrcx-team/VRCX/${COMMIT}/${upstreamPath}`,
                { signal: AbortSignal.timeout(30000) });
            assert(response.ok, `Download failed: ${response.status} ${upstreamPath}`);
            bytes = Buffer.from(await response.arrayBuffer());
            assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), expectedHash);
            await fs.writeFile(cached, bytes, { flag: 'wx' });
        }
        assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), expectedHash,
            `Pinned upstream file changed: ${upstreamPath}`);
        source[upstreamPath] = bytes.toString('utf8');
    }
    const results = [];
    async function check(name, callback) {
        const environments = [];
        const fresh = seconds => {
            const env = environment(source, seconds);
            environments.push(env);
            return env;
        };
        try {
            const detail = await callback(fresh);
            results.push({ name, passed: true, detail });
        } catch (error) {
            results.push({ name, passed: false, error: error.stack });
        } finally {
            for (const env of environments) env.db.close();
        }
    }

    await check('same_url_repeat_keeps_first_requester_and_title', fresh => {
        const e = fresh(); e.pypy();
        e.pypy({ time: 10, title: '$7. Renamed (Bob)' });
        assert.equal(e.rows().length, 1);
        assert.equal(e.rows()[0].display_name, 'Alice');
        assert.equal(e.rows()[0].video_name, '7. Test');
        return { rows: 1, later_requester: 'Bob', saved_requester: 'Alice' };
    });
    await check('same_song_different_route_inserts_two_rows', fresh => {
        const e = fresh(); e.pypy(); e.pypy({ time: 1, url: URL_B });
        assert.equal(e.rows().length, 2);
    });
    await check('cleared_state_allows_same_url_again', fresh => {
        const e = fresh(); e.pypy(); e.clearNowPlaying(); e.pypy({ time: 1 });
        assert.equal(e.rows().length, 2);
    });
    await check('wall_clock_expiry_clears_without_completion_log', fresh => {
        const e = fresh(); e.pypy({ length: 5 });
        e.setClock(6); e.updateNowPlaying();
        assert.equal(e.nowPlaying.value.url, '');
        e.pypy({ time: 6, length: 5 });
        assert.equal(e.rows().length, 2);
    });
    await check('old_buffered_inputs_can_deduplicate_differently', fresh => {
        const live = fresh(); const catchup = fresh(3600);
        for (const e of [live, catchup]) { e.pypy(); e.pypy({ time: 10, pos: 10 }); }
        assert.equal(live.rows().length, 1); assert.equal(catchup.rows().length, 2);
        return { live_rows: 1, catchup_rows: 2, scope: 'JS layer; native cutoff not emulated' };
    });
    await check('positive_position_is_recorded_without_observing_start', fresh => {
        const e = fresh(); e.pypy({ pos: 100 });
        assert.equal(e.rows().length, 1); assert.equal(e.rows()[0].created_at, at(0));
        assert(!Object.hasOwn(e.rows()[0], 'videoPos'));
    });
    await check('generic_load_alone_creates_a_row', fresh => {
        const e = fresh(); e.generic(); assert.equal(e.rows().length, 1);
        assert.equal(e.rows()[0].video_name, ''); assert.equal(e.rows()[0].user_id, '');
    });
    await check('later_marker_does_not_fill_generic_row_metadata', fresh => {
        const e = fresh(); e.generic(); e.pypy({ time: 1 });
        assert.equal(e.rows().length, 1); assert.equal(e.rows()[0].display_name, '');
        assert.equal(e.rows()[0].video_name, '');
    });
    await check('generic_rpc_world_gate', fresh => {
        const e = fresh(); e.generic({ room: RPC_ROOM }); assert.equal(e.rows().length, 0);
        e.pypy({ room: RPC_ROOM }); assert.equal(e.rows().length, 1);
    });
    await check('explicit_youtube_path_bypasses_rpc_gate', fresh => {
        const e = fresh(); e.generic({ room: RPC_ROOM, videoId: 'YouTube' });
        assert.equal(e.rows().length, 1);
        assert.equal(e.rows()[0].video_id, ''); // API disabled: input id is not persisted.
    });
    await check('generic_url_decode_preserves_reserved_escape', fresh => {
        const e = fresh(); e.generic({ url: `${URL_A}&q=a%20b%2Fc` });
        assert.equal(e.rows()[0].video_url, `${URL_A}&q=a b%2Fc`);
    });
    await check('generic_last_url_dedup_survives_now_playing_clear', fresh => {
        const e = fresh(); e.generic(); e.clearNowPlaying(); e.generic({ time: 1 });
        assert.equal(e.rows().length, 1);
        e.gameLogStore.setLastVideoUrl(''); e.generic({ time: 2 });
        assert.equal(e.rows().length, 2);
    });
    await check('random_and_blank_requester_have_identical_saved_fields', fresh => {
        const random = fresh(); const unknown = fresh();
        random.pypy({ title: '$7. Test (Random)' }); unknown.pypy({ title: '$7. Test ()' });
        assert.deepEqual(random.rows(), unknown.rows());
    });
    await check('duplicate_cached_display_names_use_first_match', fresh => {
        const e = fresh(); e.cachedUsers.clear();
        e.cachedUsers.set('usr_outside', { id: 'usr_outside', displayName: 'Alice' });
        e.cachedUsers.set('usr_inside', { id: 'usr_inside', displayName: 'Alice' });
        e.pypy(); assert.equal(e.rows()[0].user_id, 'usr_outside');
        return { room_membership_checked_by_upstream_lookup: false };
    });
    await check('vrcx_video_id_is_not_a_canonical_dance_identifier', fresh => {
        const e = fresh(); e.pypy(); assert.equal(e.rows()[0].video_id, '');
        assert.equal(e.rows()[0].video_name, '7. Test');
    });
    await check('lsmedia_and_popcorn_store_titles_in_video_url', fresh => {
        const e = fresh();
        e.addGameLogLSMedia({ dt: at(0), data: 'LSMedia 0,300,Alice,Example Film,1080p' }, ROOM);
        e.addGameLogPopcornPalace({ dt: at(1), data: 'VideoPlay(PopcornPalace) ' +
            JSON.stringify({ videoName: 'Another Film', videoPos: 20, videoLength: 300,
                displayName: 'Alice', userId: 'usr_supplied_not_used', isPaused: true }) }, ROOM);
        assert.equal(e.rows()[0].video_url, 'Example Film');
        assert.equal(e.rows()[1].video_url, 'Another Film');
        assert.equal(e.rows()[1].user_id, 'usr_alice');
        assert(!Object.hasOwn(e.rows()[1], 'isPaused'));
    });
    await check('same_second_url_collision_ignores_location_and_metadata', fresh => {
        const e = fresh(); e.pypy(); e.clearNowPlaying();
        e.pypy({ title: '$7. Changed (Bob)', room: ROOM.replace(':123', ':456') });
        assert.equal(e.attempts.length, 2); assert.equal(e.rows().length, 1);
        assert.equal(e.rows()[0].location, ROOM); assert.equal(e.rows()[0].display_name, 'Alice');
    });
    await check('delete_max_id_can_reuse_source_row_coordinate', fresh => {
        const e = fresh(); e.pypy(); e.pypy({ time: 1, url: URL_B });
        const previous = e.rows()[1];
        e.db.prepare('DELETE FROM gamelog_video_play WHERE id = ?').run(previous.id);
        e.clearNowPlaying(); e.pypy({ time: 2 });
        assert.equal(e.rows()[1].id, previous.id);
        assert.notEqual(e.rows()[1].created_at, previous.created_at);
    });
    await check('late_insert_is_missed_by_created_at_only_checkpoint', fresh => {
        const e = fresh(); e.pypy({ time: 10 }); e.pypy({ time: 0, url: URL_B });
        assert.equal(e.rows().length, 2);
        assert.equal(e.db.prepare('SELECT count(*) AS n FROM gamelog_video_play WHERE created_at > ?')
            .get(at(10)).n, 0);
        assert.equal(e.db.prepare('SELECT count(*) AS n FROM gamelog_video_play WHERE id > 1')
            .get().n, 1);
    });
    await check('zero_position_update_can_make_timer_start_nan', fresh => {
        const e = fresh(); e.pypy(); e.pypy({ time: 1, pos: 0 });
        assert(Number.isNaN(e.nowPlaying.value.startTime));
        assert.equal(e.rows().length, 1);
        return { implication: 'Do not reconstruct completion from this UI timer' };
    });

    const report = {
        tag: 'v2026.07.18', commit: COMMIT, sources_sha256: SOURCES,
        scope: 'Actual pinned JS functions and SQL; synthetic inputs, fake wall clock, in-memory DB. '
            + 'No native log watcher, IPC, network metadata, full Vue app or statistical ground truth.',
        passed: results.filter(result => result.passed).length,
        failed: results.filter(result => !result.passed).length, results
    };
    if (reportPath) await fs.writeFile(reportPath, JSON.stringify(report, null, 2) + '\n');
    process.stdout.write(JSON.stringify(report, null, 2) + '\n');
    if (report.failed) process.exitCode = 1;
}
main().catch(error => { console.error(error); process.exitCode = 1; });
