package ac.grim.grimac.checks;

import ac.grim.grimac.api.config.ConfigManager;
import ac.grim.grimac.api.storage.verbose.VerboseBuf;
import ac.grim.grimac.api.storage.verbose.Verbose;
import ac.grim.grimac.player.GrimPlayer;
import com.github.retrooper.packetevents.protocol.packettype.PacketType;
import com.github.retrooper.packetevents.protocol.packettype.PacketTypeCommon;
import ru.elytrix.efc.grim.GrimBridge;

/**
 * EFC-совместимость: база Grim Check.
 * Флаги уходят в наказания EFC через GrimBridge.
 */
public class Check {

    protected final GrimPlayer player;
    protected double violations = 0;

    private String configName;

    public Check(GrimPlayer player) {
        this.player = player;
    }

    public boolean flag() {
        violations++;
        GrimBridge.report(this, "");
        return true;
    }

    public boolean flag(Verbose.Writer writer) {
        violations++;
        GrimBridge.report(this, writer == null ? "" : writer.toString());
        return true;
    }

    public void reward() {
        violations = Math.max(0, violations - 1.0);
    }

    public VerboseBuf verbose() {
        return new VerboseBuf();
    }

    public boolean isTickPacket(PacketTypeCommon packetType) {
        return packetType == PacketType.Play.Client.PLAYER_FLYING
                || packetType == PacketType.Play.Client.PLAYER_POSITION
                || packetType == PacketType.Play.Client.PLAYER_POSITION_AND_ROTATION
                || packetType == PacketType.Play.Client.PLAYER_ROTATION;
    }

    public boolean shouldModifyPackets() {
        return true;
    }

    public boolean shouldSetback() {
        return violations >= getSetbackVL();
    }

    public void setbackIfAboveSetbackVL() {
        if (shouldSetback()) {
            executeViolationSetback();
        }
    }

    public boolean flagWithSetback() {
        boolean flagged = flag();
        setbackIfAboveSetbackVL();
        return flagged;
    }

    public void executeViolationSetback() {
        player.getSetbackTeleportUtil().executeNonSimulatingSetback();
    }

    public String getConfigName() {
        if (configName == null) {
            CheckData data = getClass().getAnnotation(CheckData.class);
            if (data == null || "DEFAULT".equals(data.configName())) {
                configName = data == null ? getClass().getSimpleName() : data.name();
            } else {
                configName = data.configName();
            }
        }
        return configName;
    }

    public double getSetbackVL() {
        CheckData data = getClass().getAnnotation(CheckData.class);
        return data == null ? 25.0 : data.setback();
    }

    public void onReload(ConfigManager config) {
    }
}
