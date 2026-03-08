import Foundation

// MARK: - Models
struct F1Season: Codable {
    let season: Int
    let series: String
    let source: SourceInfo
    var events: [F1Event]
}

struct SourceInfo: Codable {
    let calendar: String
    let sessionsNote: String
    
    enum CodingKeys: String, CodingKey {
        case calendar
        case sessionsNote = "sessions_note"
    }
}

struct F1Event: Codable {
    let round: Int?
    let eventType: String
    let eventName: String
    let country: String
    let location: String
    let startDate: String
    let endDate: String
    let url: String
    var sessions: [F1Session]
    
    enum CodingKeys: String, CodingKey {
        case round
        case eventType = "event_type"
        case eventName = "event_name"
        case country, location
        case startDate = "start_date"
        case endDate = "end_date"
        case url
        case sessions
    }
}

struct F1Session: Codable {
    let date: String
    let session: String
    let startTimeLocal: String?
    let endTimeLocal: String?
    
    enum CodingKeys: String, CodingKey {
        case date
        case session
        case startTimeLocal = "start_time_local"
        case endTimeLocal = "end_time_local"
    }
}

// MARK: - Output Models (with ISO date format)
struct F1SessionISO: Codable {
    let date: String
    let session: String
    let startDatetimeLocal: String?
    let endDatetimeLocal: String?
    
    enum CodingKeys: String, CodingKey {
        case date, session
        case startDatetimeLocal = "start_datetime_local"
        case endDatetimeLocal = "end_datetime_local"
    }
}

struct F1EventISO: Codable {
    let round: Int?
    let eventType: String
    let eventName: String
    let country: String
    let location: String
    let startDate: String
    let endDate: String
    let url: String
    var sessions: [F1SessionISO]
    
    enum CodingKeys: String, CodingKey {
        case round
        case eventType = "event_type"
        case eventName = "event_name"
        case country, location
        case startDate = "start_date"
        case endDate = "end_date"
        case url
        case sessions
    }
}

struct F1SeasonISO: Codable {
    let season: Int
    let series: String
    let source: SourceInfo
    var events: [F1EventISO]
}

// MARK: - Converter
func convertToISO() {
    let fileManager = FileManager.default
    // Use the absolute path or run in the same directory
    let inputURL = URL(fileURLWithPath: "/Users/junghoon/Downloads/f1_2026_schedule_detailed.json")
    let outputURL = URL(fileURLWithPath: "/Users/junghoon/Downloads/f1_2026_schedule_detailed_iso_local_swift.json")
    
    do {
        let data = try Data(contentsOf: inputURL)
        let decoder = JSONDecoder()
        let originalSeason = try decoder.decode(F1Season.self, from: data)
        
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .withoutEscapingSlashes]
        
        var isoEvents: [F1EventISO] = []
        
        for event in originalSeason.events {
            var isoSessions: [F1SessionISO] = []
            
            for session in event.sessions {
                // Formatting date + time to ISO8601 string (Local Time without Z)
                // e.g., date: "2026-03-06", time: "01:30" => "2026-03-06T01:30:00"
                
                var startISO: String? = nil
                if let startTime = session.startTimeLocal {
                    startISO = "\(session.date)T\(startTime):00"
                }
                
                var endISO: String? = nil
                if let endTime = session.endTimeLocal {
                    endISO = "\(session.date)T\(endTime):00"
                } // testing days might have null times or different dates, but for now it's matching simple logic.
                
                let newSession = F1SessionISO(
                    date: session.date,
                    session: session.session,
                    startDatetimeLocal: startISO,
                    endDatetimeLocal: endISO
                )
                isoSessions.append(newSession)
            }
            
            let isoEvent = F1EventISO(
                round: event.round,
                eventType: event.eventType,
                eventName: event.eventName,
                country: event.country,
                location: event.location,
                startDate: event.startDate,
                endDate: event.endDate,
                url: event.url,
                sessions: isoSessions
            )
            isoEvents.append(isoEvent)
        }
        
        let isoSeason = F1SeasonISO(
            season: originalSeason.season,
            series: originalSeason.series,
            source: originalSeason.source,
            events: isoEvents
        )
        
        let encodedData = try encoder.encode(isoSeason)
        try encodedData.write(to: outputURL)
        print("✅변환 완료! 경로: \(outputURL.path)")
        
    } catch {
        print("❌오류 발생: \(error)")
    }
}

convertToISO()
