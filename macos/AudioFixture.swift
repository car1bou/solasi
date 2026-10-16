import Foundation

@main
struct AudioFixture {
    static func main() throws {
        var timeline = PCMSequence()
        let first = try timeline.packet(samples:[0, -1, 1, 0.5], sampleTime:100)
        assert(first.count == 28)
        assert(Array(first.suffix(8)) == [0,0,0,128,255,127,0,64])
        let next = try timeline.packet(samples:[0,0],sampleTime:110)
        assert(Array(next.prefix(8)) == [1,0,0,0,0,0,0,0])
        assert(Array(next.dropFirst(8).prefix(8)) == [10,0,0,0,0,0,0,0])
        assert(timeline.end == 12)
        do { _ = try timeline.packet(samples:[0],sampleTime:105); assertionFailure() } catch {}
        var lifecycle = CaptureGuard()
        assert(lifecycle.acceptsPermission)
        lifecycle.finish()
        assert(!lifecycle.acceptsPermission)
        assert(!lifecycle.recoverOnFreshInput())
        var recovery = CaptureGuard()
        recovery.waitForInput()
        assert(!recovery.recovered)
        assert(recovery.recoverOnFreshInput())
        assert(recovery.recovered)
        recovery.waitForInput()
        assert(!recovery.recoverOnFreshInput())
        print("Native PCM silence/gap/clipping and cancelled permission/recovery fixtures passed")
    }
}
