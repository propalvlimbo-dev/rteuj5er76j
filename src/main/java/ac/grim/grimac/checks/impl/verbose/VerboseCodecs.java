package ac.grim.grimac.checks.impl.verbose;

import com.github.retrooper.packetevents.protocol.player.ClientVersion;
import com.github.retrooper.packetevents.protocol.world.states.type.StateType;

/**
 * EFC-совместимость: Grim VerboseCodecs (только используемые кодировщики).
 */
public final class VerboseCodecs {

    private VerboseCodecs() {
    }

    public static int enumId(Enum<?> value) {
        return value == null ? -1 : value.ordinal();
    }

    public static int block(StateType type, ClientVersion version) {
        return 0;
    }
}
