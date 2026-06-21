//
//  Item.swift
//  WeMightBeCooked
//
//  Created by Michelle Dong on 6/20/26.
//

import Foundation
import SwiftData

@Model
final class Item {
    var timestamp: Date
    
    init(timestamp: Date) {
        self.timestamp = timestamp
    }
}
