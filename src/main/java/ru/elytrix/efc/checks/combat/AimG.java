package ru.elytrix.efc.checks.combat;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import kireiko.dev.millennium.vectors.Vec2f;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.player.PlayerMoveEvent;
import ru.elytrix.efc.ElytrixFuckCheats;
import ru.elytrix.efc.check.Category;
import ru.elytrix.efc.check.Check;

/**
 * Aim.G: MX-Project AimPatternCheck (Unlicense), логика 1:1.
 * Выборка 100 вторых разностей поворота. Флаг: больше 3 совпадений
 * |x_i - y_{i-1}| точнее 1e-4, либо повтор тройки поворотов
 * (|x|&gt;1 или |y|&gt;1, обе &gt;0.26). Буфер 2.5, затухание 0.3.
 * Вектора — оригинальный MX Vec2f. Блокировка атак MX (5 сек)
 * не портирована — только флаг.
 */
public final class AimG extends Check {

    private static final int PATTERN_LENGTH = 3;
    private static final int SAMPLE_SIZE = 100;
    private static final int MIN_START_INDEX_GAP = 3;
    private static final float VL_LIMIT = 2.5F;
    private static final float VL_FADE = 0.3F;

    private static final class State {
        float oldDx;
        float oldDy;
        final List<Vec2f> sample = new ArrayList<>();
        float buffer;
        int longTermRating;
        int toCheck;
    }

    private final Map<UUID, State> states = new ConcurrentHashMap<>();

    public AimG(ElytrixFuckCheats plugin) {
        super(plugin, "Aim", "G", Category.COMBAT);
    }

    @Override
    public void onQuit(UUID uuid) {
        states.remove(uuid);
    }

    @EventHandler
    public void onMove(PlayerMoveEvent event) {
        float dx = wrap(event.getTo().getYaw() - event.getFrom().getYaw());
        float dy = event.getTo().getPitch() - event.getFrom().getPitch();
        if (dx == 0.0F && dy == 0.0F) {
            return;
        }
        Player player = event.getPlayer();
        State state = states.computeIfAbsent(player.getUniqueId(), key -> new State());
        float yawFactor = dx - state.oldDx;
        float pitchFactor = dy - state.oldDy;
        state.sample.add(new Vec2f(yawFactor, pitchFactor));
        if (state.sample.size() >= SAMPLE_SIZE) {
            processSample(player, state);
            state.sample.clear();
        }
        state.oldDx = dx;
        state.oldDy = dy;
    }

    private void processSample(Player player, State state) {
        boolean flagged = false;
        List<Float> rawPatterns = new ArrayList<>();
        List<Float> filteredPatterns = new ArrayList<>();
        for (int i = 0; i < SAMPLE_SIZE; i++) {
            if (i > 0 && Math.abs(state.sample.get(i).getX()) > 1.0) {
                rawPatterns.add(Math.abs(state.sample.get(i).getX() - state.sample.get(i - 1).getY()));
            }
        }
        for (float x : rawPatterns) {
            if (x < 1e-4) {
                filteredPatterns.add(x);
            }
        }
        if (filteredPatterns.size() > 3) {
            flagged = true;
            if (state.buffer++ >= VL_LIMIT) {
                flag(player, "patterns=" + filteredPatterns.size());
                state.buffer -= 1.0F;
            }
        }
        if (!flagged) {
            List<Vec2f> patterns = new ArrayList<>();
            int currentSampleSize = state.sample.size();
            for (int i = 0; i <= currentSampleSize - PATTERN_LENGTH; ++i) {
                for (int j = i + MIN_START_INDEX_GAP; j <= currentSampleSize - PATTERN_LENGTH; ++j) {
                    Vec2f pattern = null;
                    for (int k = 0; k < PATTERN_LENGTH; ++k) {
                        Vec2f first = state.sample.get(i + k);
                        Vec2f second = state.sample.get(j + k);
                        if (first.equals(second)) {
                            pattern = first;
                            break;
                        }
                    }
                    if (pattern != null && !patterns.contains(pattern)) {
                        patterns.add(pattern);
                    }
                }
            }
            state.longTermRating += patterns.size();
            state.toCheck++;
            if (state.toCheck >= 8) {
                state.toCheck = 0;
                state.longTermRating = 0;
            }
            for (Vec2f vec : patterns) {
                float x = Math.abs(vec.getX());
                float y = Math.abs(vec.getY());
                if ((x > 1.0 || y > 1.0) && (x > 0.26 && y > 0.26)) {
                    flagged = true;
                    if (state.buffer++ >= VL_LIMIT) {
                        flag(player, "pattern=" + vec.getX() + "," + vec.getY());
                        state.buffer -= 1.0F;
                    }
                    break;
                }
            }
        }
        if (!flagged) {
            state.buffer = Math.max(0, state.buffer - VL_FADE);
        }
    }

    private void flag(Player player, String details) {
        flag(plugin.getDataManager().get(player), details);
    }

    private static float wrap(float yaw) {
        while (yaw > 180.0F) {
            yaw -= 360.0F;
        }
        while (yaw < -180.0F) {
            yaw += 360.0F;
        }
        return yaw;
    }
}
